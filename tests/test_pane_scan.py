"""E1 — Scan de pane : une seule implémentation, prouvée par différentiel.

Le repo portait TROIS parsings du même pane tmux :

    scripts/agent-bridge/agent.py     _parse_pane_state()   marqueurs externalisés
    web/backend/multi_agent/cache.py  blob bash             chaînes en dur
    scripts/debug-color.py            blob bash             chaînes en dur

Les deux blobs bash étaient figés sur Claude Code (`"$pane_cmd" == "claude"`,
`grep "esc to interrupt"`, `grep "❯"`…). C'est exactement le mécanisme du bug
d'origine : une hypothèse recopiée, qui dérive.

E1 les génère depuis markers.<cli>.yaml (engines.build_pane_scan). Ce module
prouve, sur des panes réels, que le bash généré et `_parse_pane_state` donnent
le MÊME état — champ par champ. Une divergence future casse ces tests.
"""
import os
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")


def _find_project_root(start, markers=('CLAUDE.md', '.git')):
    current = os.path.realpath(start)
    while current != os.path.dirname(current):
        if any(os.path.exists(os.path.join(current, m)) for m in markers):
            return current
        current = os.path.dirname(current)
    raise FileNotFoundError(f"Marqueur {markers} introuvable depuis {start}")


BASE_DIR = _find_project_root(os.path.dirname(os.path.realpath(__file__)))
BRIDGE_DIR = os.path.join(BASE_DIR, 'scripts', 'agent-bridge')
sys.path.insert(0, BRIDGE_DIR)

import engines  # noqa: E402
import agent as agent_mod  # noqa: E402

MARKERS = engines.load_markers('claude')


# ── Panes réels (Claude Code) ───────────────────────────────────────────────

STATUS = "  bypass permissions on (shift+tab to cycle)"

PANES = {
    'idle': (
        "Je suis prêt.\n"
        "❯ \n"
        f"{STATUS}\n"
    ),
    'busy': (
        "Analyse en cours…\n"
        f"{STATUS} · esc to interrupt\n"
    ),
    # Piège historique : Claude lance des sous-agents → « ❯ » visible ALORS QUE
    # l'agent travaille. Seul « esc to interrupt » fait foi.
    'busy_with_prompt_visible': (
        "❯ \n"
        f"{STATUS} · esc to interrupt · 2 bashes\n"
    ),
    'has_bashes': (
        "❯ \n"
        f"{STATUS} · 3 bashes\n"
    ),
    'scroll': (
        "❯ \n"
        f"{STATUS} ↓\n"
    ),
    'plan_mode': (
        "plan mode on\n"
        "❯ \n"
        f"{STATUS}\n"
    ),
    'waiting_select': (
        "1. Oui\n2. Non\n"
        "Enter to select\n"
        f"{STATUS}\n"
    ),
    'compacting': (
        "Compacting conversation…\n"
        f"{STATUS} · esc to interrupt\n"
    ),
    'compacted': (
        "Conversation compacted · ctrl+o for history\n"
        "❯ \n"
        f"{STATUS}\n"
    ),
    'compacted_and_prompt_reloaded': (
        "Conversation compacted · ctrl+o for history\n"
        "Lecture de prompts/345-analyse/345-500-system.md\n"
        "❯ \n"
        f"{STATUS}\n"
    ),
    'context_pct': (
        "❯ \n"
        f"{STATUS} · 12% until auto-compact\n"
    ),
    'context_pct_alt': (
        "❯ \n"
        f"{STATUS} · auto-compact: 3%\n"
    ),
    'context_limit': (
        "Context limit reached\n"
        f"{STATUS}\n"
    ),
    'api_error': (
        "API Error: 401\nAPI Error: 401\nAPI Error: 401\n"
        f"{STATUS}\n"
    ),
    # bp_line absente alors que le process tourne = sonde de vie négative
    'no_status_line': "quelque chose d'inattendu\n",
    'model_change': (
        "/model claude-opus-4-8\n"
        "❯ \n"
        f"{STATUS}\n"
    ),
    'empty': "",
}

CASES = [
    (name, out, pane_cmd)
    for name, out in PANES.items()
    for pane_cmd in ('claude', 'node', 'bash')
]


def run_bash_eval(markers, out, pane_cmd, agent_id):
    """Exécute le corps bash généré, hors tmux : $out / $pane_cmd injectés."""
    script = (
        'out="$1"; pane_cmd="$2"; id="$3"; '
        + engines.build_pane_eval(markers)
    )
    r = subprocess.run(['bash', '-c', script, '_', out, pane_cmd, agent_id],
                       capture_output=True, text=True, timeout=15)
    assert r.returncode == 0, r.stderr
    line = r.stdout.strip()
    parts = line.split(':')
    assert len(parts) == len(engines.PANE_FIELDS), f"champs: {line!r}"
    d = dict(zip(engines.PANE_FIELDS, parts))
    return {
        'busy': d['busy'] == '1',
        'has_bashes': d['has_bashes'] == '1',
        'has_down': d['has_down'] == '1',
        'plan_mode': d['plan_mode'] == '1',
        'waiting_approval': d['waiting_approval'] == '1',
        'login_required': d['login_required'] == '1',
        'compacted': d['compacted'] == '1',
        'context_pct': int(d['context_pct']),
        'done_compacting': d['done_compacting'] == '1',
        'prompt_loaded': d['prompt_loaded'] == '1',
        'context_limit': d['context_limit'] == '1',
        'api_error': d['api_error'] == '1',
        'model_change': d['model_change'] == '1',
        'claude_alive': d['claude_alive'] == '1',
    }


class TestBashPythonParity:
    """LE test : bash généré == Python, sur chaque pane, pour chaque champ."""

    @pytest.mark.parametrize('name,out,pane_cmd', CASES,
                             ids=[f"{n}-{c}" for n, out, c in CASES])
    def test_same_state(self, name, out, pane_cmd):
        aid = '345-500'
        got = run_bash_eval(MARKERS, out, pane_cmd, aid)
        expected = agent_mod._parse_pane_state(out, pane_cmd, aid)
        diffs = {k: (expected[k], got[k]) for k in expected if expected[k] != got[k]}
        assert not diffs, (
            f"divergence bash/Python sur le pane « {name} » (pane_cmd={pane_cmd}) : "
            f"{ {k: f'py={v[0]!r} sh={v[1]!r}' for k, v in diffs.items()} }"
        )


class TestSemantics:
    """Quelques invariants métier, indépendamment de la parité."""

    def test_subagents_prompt_visible_but_busy(self):
        """Piège : « ❯ » présent ET « esc to interrupt » → occupé."""
        st = run_bash_eval(MARKERS, PANES['busy_with_prompt_visible'], 'claude', '300')
        assert st['busy'] is True

    def test_dead_process_is_never_busy(self):
        st = run_bash_eval(MARKERS, PANES['busy'], 'bash', '300')
        assert st['claude_alive'] is False
        assert st['busy'] is False

    def test_missing_status_line_flags_api_error(self):
        st = run_bash_eval(MARKERS, PANES['no_status_line'], 'claude', '300')
        assert st['api_error'] is True

    def test_prompt_loaded_requires_compaction_done(self):
        st = run_bash_eval(MARKERS, PANES['compacted_and_prompt_reloaded'], 'claude', '345-500')
        assert st['done_compacting'] is True
        assert st['prompt_loaded'] is True

    @pytest.mark.parametrize('pane,expected', [
        ('context_pct', 12), ('context_pct_alt', 3), ('idle', -1),
    ])
    def test_context_pct(self, pane, expected):
        assert run_bash_eval(MARKERS, PANES[pane], 'claude', '300')['context_pct'] == expected


class TestInjectionSafety:
    """Les marqueurs viennent d'un fichier YAML : ils finissent dans un script
    bash. Un marqueur mal échappé serait une exécution de commande."""

    @pytest.mark.parametrize('evil', [
        '"; id; echo "',
        "'; id; #",
        '$(id)',
        '`id`',
    ])
    def test_marker_cannot_inject(self, evil):
        m = dict(MARKERS)
        m['status_line'] = evil
        st = run_bash_eval(m, "rien\n", 'claude', '300')
        assert isinstance(st['busy'], bool)   # a tourné sans exécuter `id`

    def test_generated_script_quotes_every_marker(self):
        """Aucun marqueur ne doit apparaître nu dans le script généré."""
        script = engines.build_pane_eval(MARKERS)
        assert "grep -F 'bypass permissions'" in script or \
               'grep -F "bypass permissions"' in script, \
               "status_line doit être un littéral quoté"


class TestGeneratedScanShape:
    def test_scan_uses_canonical_address(self):
        s = engines.build_pane_scan(MARKERS, 'Z')
        assert '${s#agent-}' in s

    def test_scan_captures_once_per_agent(self):
        """Contrat de perf historique : un seul capture-pane par agent."""
        s = engines.build_pane_scan(MARKERS, 'A')
        assert s.count('tmux capture-pane') == 1
        assert s.startswith('for s in "$@"; do')

    def test_field_count_matches_consumer(self):
        assert len(engines.PANE_FIELDS) == 15

    def test_codex_scan_builds(self):
        """Les marqueurs codex sont relevés → le scan se génère."""
        s = engines.build_pane_scan(engines.load_markers('codex'), 'A')
        assert 'to interrupt' in s
        assert 'context left' in s


class TestNoRemainingBashDuplication:
    """Les deux blobs bash en dur doivent avoir disparu."""

    @pytest.mark.parametrize('rel', [
        'web/backend/multi_agent/cache.py',
        'scripts/debug-color.py',
    ])
    def test_no_hardcoded_ui_strings(self, rel):
        """Même discipline que A1 (test_markers_externalized) : on inspecte les
        littéraux du CODE via tokenize — un commentaire qui décrit un marqueur
        n'est pas un couplage."""
        import io
        import tokenize
        path = os.path.join(BASE_DIR, rel)
        literals = []
        with open(path, 'rb') as f:
            for tok in tokenize.tokenize(f.readline):
                if tok.type == tokenize.STRING:
                    literals.append(tok.string)
        code = '\n'.join(literals)
        for ui in ('esc to interrupt', 'bypass permissions', 'Enter to select',
                   'until auto-compact', 'Conversation compacted', 'plan mode on'):
            assert ui not in code, f"{rel} : chaîne d'UI en dur — {ui!r}"

    @pytest.mark.parametrize('rel', [
        'web/backend/multi_agent/cache.py',
        'scripts/debug-color.py',
    ])
    def test_uses_generated_scan(self, rel):
        src = open(os.path.join(BASE_DIR, rel), encoding='utf-8').read()
        assert 'build_pane_scan' in src or 'build_pane_eval' in src


# ═══════════════════════════════════════════════════════════════════════════
# MOTEUR CODEX — mêmes exigences, mêmes preuves.
#
# Les panes ci-dessous sont RECONSTRUITS À PARTIR DES SNAPSHOTS DE TEST de
# openai/codex (crate `tui`, fichiers *.snap). Un snapshot insta est le buffer
# réellement rendu par le TUI : c'est exactement ce que `tmux capture-pane`
# produirait. Ce ne sont donc pas des panes inventés.
#
# Sources citées dans scripts/agent-bridge/markers.codex.yaml.
# ═══════════════════════════════════════════════════════════════════════════

MARKERS_CODEX = engines.load_markers('codex')

CODEX_FOOTER_IDLE = "  ? for shortcuts                                            100% context left  "
CODEX_FOOTER_72 = "  ? for shortcuts                                             72% context left  "
CODEX_COMPOSER = "› Ask Codex to do anything                                                     "

CODEX_PANES = {
    # [Snapshot: chat_composer footer_mode_* + footer_shortcuts_default]
    'idle': f"{CODEX_COMPOSER}\n{CODEX_FOOTER_IDLE}\n",

    # [Snapshot: status_indicator_widget__tests__renders_with_working_header]
    # PIÈGE STRUCTUREL : le composer « › » RESTE affiché pendant le travail.
    # L'heuristique de Claude Code (« prompt visible = idle ») conclurait idle.
    'busy': (
        "• Working (0s • esc to interrupt)                                              \n"
        f"{CODEX_COMPOSER}\n{CODEX_FOOTER_72}\n"
    ),

    # [Snapshot: renders_remapped_interrupt_hint] — la touche est remappable
    'busy_remapped_key': (
        "Working (0s • f12 to interrupt)                                                \n"
        f"{CODEX_COMPOSER}\n{CODEX_FOOTER_72}\n"
    ),

    # [Snapshot: renders_with_queued_messages]
    'busy_with_queue': (
        "• Working (0s • esc to interrupt)                                              \n"
        " ↳ first                                                                       \n"
        " ↳ second                                                                      \n"
        "   alt + ↑ edit                                                                \n"
        f"{CODEX_FOOTER_72}\n"
    ),

    # [Snapshot: bottom_pane__unified_exec_footer__tests__render_many_sessions]
    'has_bashes': (
        f"{CODEX_COMPOSER}\n"
        "  123 background terminals running · /ps to view ·                             \n"
        f"{CODEX_FOOTER_IDLE}\n"
    ),

    # [Snapshot: approval_overlay__tests__approval_overlay_permissions_prompt]
    'approval': (
        "  Would you like to run the following command?                                 \n"
        "  $ cat /tmp/readme.txt                                                        \n"
        "› 1. Yes, proceed (y)                                                          \n"
        "  2. No, and tell Codex what to do differently (esc)                           \n"
        "  Press enter to confirm or esc to cancel                                      \n"
        f"{CODEX_FOOTER_IDLE}\n"
    ),

    # [Source: chatwidget/replay.rs:176 — add_info_message("Context compacted")]
    'compacted': (
        "Context compacted                                                              \n"
        f"{CODEX_COMPOSER}\n{CODEX_FOOTER_IDLE}\n"
    ),
    'compacted_and_prompt_reloaded': (
        "Context compacted                                                              \n"
        "Lecture de prompts/345-analyse/345-500-system.md                               \n"
        f"{CODEX_COMPOSER}\n{CODEX_FOOTER_IDLE}\n"
    ),

    # [Source: bottom_pane/footer.rs:149 — CollaborationModeIndicator::Plan]
    'plan_mode': (
        f"{CODEX_COMPOSER}\n"
        "  Plan mode                                                  72% context left  \n"
    ),
    'plan_mode_suggestion': (
        "Create a plan?  shift + tab use Plan mode   esc dismiss\n"
        f"{CODEX_COMPOSER}\n{CODEX_FOOTER_IDLE}\n"
    ),

    # [Source: history_cell/notices.rs:213 — format!("■ {message}").red()]
    'api_error': (
        "■ Rate limit exceeded                                                          \n"
        "■ Rate limit exceeded                                                          \n"
        "■ Rate limit exceeded                                                          \n"
        f"{CODEX_FOOTER_IDLE}\n"
    ),

    # [Source: footer.rs:1015 — « {used} used » quand le % est inconnu]
    'tokens_used_no_pct': f"{CODEX_COMPOSER}\n  ? for shortcuts                     123K used  \n",

    # Ligne de statut absente + process vivant = sonde de vie négative
    'no_status_line': "quelque chose d'inattendu\n",

    # [Source: onboarding/auth.rs:444,460]
    'login_expired': (
        "  1. Sign in with ChatGPT                                                      \n"
        "  2. Provide your own API key                                                  \n"
    ),
    'empty': "",
}

CODEX_CASES = [
    (name, out, cmd)
    for name, out in CODEX_PANES.items()
    for cmd in ('codex', 'node', 'bash')
]


class TestCodexBashPythonParity:
    """Même différentiel que pour claude : bash généré == Python, champ par champ."""

    @pytest.mark.parametrize('name,out,pane_cmd', CODEX_CASES,
                             ids=[f"{n}-{c}" for n, out, c in CODEX_CASES])
    def test_same_state(self, name, out, pane_cmd):
        aid = '345-500'
        got = run_bash_eval(MARKERS_CODEX, out, pane_cmd, aid)
        expected = agent_mod._parse_pane_state(out, pane_cmd, aid, markers=MARKERS_CODEX)
        diffs = {k: (expected[k], got[k]) for k in expected if expected[k] != got[k]}
        assert not diffs, (
            f"divergence bash/Python sur le pane codex « {name} » "
            f"(pane_cmd={pane_cmd}) : "
            f"{ {k: f'py={v[0]!r} sh={v[1]!r}' for k, v in diffs.items()} }"
        )


class TestCodexSemantics:
    """Le piège structurel, et les [NA] assumés."""

    def _st(self, pane, cmd='codex'):
        return run_bash_eval(MARKERS_CODEX, CODEX_PANES[pane], cmd, '300')

    def test_busy_even_though_composer_is_visible(self):
        """LE piège. Avec l'algorithme de Claude Code (busy_scope=status_line),
        le « › » visible ferait conclure idle → prompts envoyés par-dessus une
        réponse en cours, réponses tronquées."""
        assert '›' in CODEX_PANES['busy']          # le composer EST visible
        assert self._st('busy')['busy'] is True    # et pourtant : occupé

    def test_claude_algorithm_would_get_it_wrong(self):
        """Preuve directe : le même pane, parsé avec busy_scope=status_line,
        donne le MAUVAIS résultat. C'est ce que ferait un portage naïf — et
        c'est indétectable en production : l'agent est simplement toujours vu
        libre, on lui envoie des prompts par-dessus une réponse en cours."""
        naive = dict(MARKERS_CODEX)
        naive['busy_scope'] = 'status_line'
        assert run_bash_eval(naive, CODEX_PANES['busy'], 'codex', '300')['busy'] is False
        assert agent_mod._parse_pane_state(
            CODEX_PANES['busy'], 'codex', '300', markers=naive)['busy'] is False

    def test_remapped_interrupt_key_still_detected(self):
        """La touche d'interruption est remappable : le marqueur ne doit pas en
        dépendre (« f12 to interrupt » aussi bien que « esc to interrupt »)."""
        assert self._st('busy_remapped_key')['busy'] is True

    def test_idle(self):
        assert self._st('idle')['busy'] is False

    def test_dead_process_never_busy(self):
        assert self._st('busy', cmd='bash')['claude_alive'] is False
        assert self._st('busy', cmd='bash')['busy'] is False

    def test_context_pct(self):
        assert self._st('busy')['context_pct'] == 72
        assert self._st('idle')['context_pct'] == 100

    def test_tokens_used_yields_no_pct(self):
        """« 123K used » : pas de pourcentage → -1, pas 123."""
        assert self._st('tokens_used_no_pct')['context_pct'] == -1

    def test_background_terminals(self):
        assert self._st('has_bashes')['has_bashes'] is True

    def test_queued_messages_do_not_break_busy(self):
        assert self._st('busy_with_queue')['busy'] is True

    def test_waiting_approval(self):
        assert self._st('approval')['waiting_approval'] is True

    def test_compaction_done(self):
        assert self._st('compacted')['done_compacting'] is True

    def test_prompt_reloaded_after_compaction(self):
        st = run_bash_eval(MARKERS_CODEX,
                           CODEX_PANES['compacted_and_prompt_reloaded'], 'codex', '345-500')
        assert st['done_compacting'] is True and st['prompt_loaded'] is True

    def test_plan_mode(self):
        assert self._st('plan_mode')['plan_mode'] is True

    def test_plan_mode_suggestion_is_not_active_mode(self):
        assert self._st('plan_mode_suggestion')['plan_mode'] is False

    def test_plan_mode_in_old_scrollback_is_ignored(self):
        pane = "Plan mode mentionné dans une ancienne réponse\n" + CODEX_PANES['idle']
        assert run_bash_eval(MARKERS_CODEX, pane, 'codex', '300')['plan_mode'] is False

    def test_api_error(self):
        assert self._st('api_error')['api_error'] is True

    def test_missing_status_line_flags_api_error(self):
        assert self._st('no_status_line')['api_error'] is True

    # ── Les [NA] : signaux qui n'existent pas dans ce TUI ──

    def test_compaction_in_progress_is_na(self):
        """Codex n'affiche rien pendant la compaction. Inventer une chaîne
        mettrait des agents en rouge « compaction » à tort, en permanence."""
        assert MARKERS_CODEX['compaction']['in_progress'] == engines.NEVER_MATCH
        for pane in CODEX_PANES:
            assert run_bash_eval(MARKERS_CODEX, CODEX_PANES[pane], 'codex', '300')['compacted'] is False

    def test_na_markers_never_match_any_pane(self):
        """Un [NA] doit être inerte, jamais universel. Une chaîne VIDE, elle,
        matcherait TOUS les panes — d'où le sentinelle explicite."""
        for key in ('survey', 'scroll_indicator', 'context_limit'):
            assert MARKERS_CODEX[key] == engines.NEVER_MATCH
        for pane in CODEX_PANES:
            st = run_bash_eval(MARKERS_CODEX, CODEX_PANES[pane], 'codex', '300')
            assert st['has_down'] is False
            assert st['context_limit'] is False


class TestCodexMarkersProvenance:
    """Chaque marqueur codex doit porter sa source. Sans citation, une valeur est
    indistinguable d'une invention."""

    @pytest.fixture(scope='class')
    def raw(self):
        return open(os.path.join(BRIDGE_DIR, 'markers.codex.yaml'), encoding='utf-8').read()

    def test_no_todo_sentinel_remains(self):
        flat = list(engines._walk_values(
            yaml.safe_load(open(os.path.join(BRIDGE_DIR, 'markers.codex.yaml'), encoding='utf-8'))))
        assert engines.TODO_SENTINEL not in flat

    def test_cites_the_upstream_repo(self, raw):
        assert 'github.com/openai/codex' in raw

    def test_every_marker_block_has_a_source(self, raw):
        """Chaque section [D] cite un fichier source ou un snapshot."""
        blocks = [b for b in raw.split('# ── ') if b.strip()]
        documented = [b for b in blocks if b.startswith('[D]')]
        assert len(documented) >= 12
        for b in documented:
            head = b.splitlines()[0]
            assert '[Source:' in b or '[Snapshot' in b, f"section sans source : {head}"

    def test_na_blocks_explain_why(self, raw):
        na = [b for b in raw.split('# ── ') if b.startswith('[NA]')]
        assert len(na) >= 3
        for b in na:
            assert len(b) > 120, "un [NA] doit être justifié, pas juste déclaré"

    def test_busy_marker_is_keymap_independent(self, raw):
        """« esc to interrupt » serait faux si l'utilisateur remappe la touche."""
        assert MARKERS_CODEX['busy_markers'] == ['to interrupt']
        assert 'REMAPPABLE' in raw or 'remappable' in raw
