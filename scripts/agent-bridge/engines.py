#!/usr/bin/env python3
"""engines.py — Couche « moteur CLI » : source unique de vérité côté Python.

Pendant de scripts/engines.sh. Le bridge pilote un CLI agentique interactif
dans tmux et déduit son état par parsing visuel du pane. Les chaînes d'UI sont
donc SPÉCIFIQUES AU MOTEUR : ce module choisit le bon fichier de marqueurs.

    markers.claude.yaml   ← moteur `claude` (Claude Code)
    markers.codex.yaml    ← moteur `codex`  (OpenAI Codex CLI)
    markers.yaml          ← lien symbolique vers markers.claude.yaml (rétro-compat)

Le moteur est transmis par agent.sh / infra.sh via la variable d'environnement
AGENT_CLI. Absente → `claude` (comportement historique v3.0.x inchangé).

DISCIPLINE ANTI-HALLUCINATION
-----------------------------
Les marqueurs d'un moteur ne peuvent PAS être devinés : ce sont les chaînes
réellement rendues par son TUI. Tout marqueur laissé au sentinelle TODO fait
échouer le chargement immédiatement (fail-fast), plutôt que de dégrader
silencieusement la détection busy/ready — qui se traduirait par des agents
figés ou des réponses tronquées, sans message d'erreur.

Pour renseigner un moteur : scripts/agent-bridge/capture-markers.sh <cli>
"""

import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - même message que agent.py
    raise SystemExit(
        "[engines] Dépendance manquante : PyYAML. pip install -r requirements.txt"
    )

# Moteurs supportés — miroir de ENGINES dans scripts/engines.sh
ENGINES = ("claude", "codex")
ENGINE_DEFAULT = "claude"

# Tables du moteur — miroirs de engine_config_env / engine_bypass_flag /
# engine_model_prefix (scripts/engines.sh). Verrouillées par
# tests/test_no_engine_hardcoding.py::TestEngineTablesAgree.
ENGINE_CONFIG_ENV = {"claude": "CLAUDE_CONFIG_DIR", "codex": "CODEX_HOME"}
ENGINE_BYPASS_FLAG = {
    "claude": "--dangerously-skip-permissions",
    "codex": "--dangerously-bypass-approvals-and-sandbox",
}
ENGINE_MODEL_PREFIX = {"claude": "claude-", "codex": "gpt-"}

# Répertoire temporaire privé par propriétaire (agent ou session keepalive).
# Au démarrage, Codex supprime sous $TMPDIR/arg0 les répertoires d'outils qu'il
# juge abandonnés (« failed to clean up stale arg0 temp dirs ») : avec un /tmp
# partagé, neuf Codex lancés ensemble ont supprimé apply_patch et le wrapper
# sandbox les uns des autres (constat mx81, 2026-10-10). Isolé par
# propriétaire, ce nettoyage ne voit plus que ses propres répertoires. Les
# chemins /tmp/codex-* sont exclus du vieillissement par tmpfiles.
ENGINE_PRIVATE_TMPDIR = {"codex": "/tmp/codex-{owner}"}
_OWNER_RE = r"[A-Za-z0-9_-]+"

# E1 : la capacité d'effort d'un modèle est une connaissance moteur.
# Niveaux étendus X (xhigh) / MAX (max) relevés sur TUI réel :
# - Claude Code : /effort low|medium|high|xhigh|max sur les modèles Claude 5
#   [Relevé: hub mx9, 2026-07-28 ; Claude Code 2.1.295 sur mx3, 2026-10-09 ;
#   claude-fable-5-2 : Claude Code 2.1.319 sur mx30, 2026-11-10 — `/effort
#   max` → « ◈ max », `/effort ultracode on|off` → « Ultracode off. Effort
#   stays max. »] ;
# - Codex : picker « Select Reasoning Level » 1=Low … 4=Extra high,
#   5=More reasoning… → « Advanced Reasoning » 1=Max [Relevé: mx6, TUI
#   0.144.x, 2026-07-28 ; 0.153.3, 2026-09-04 ; mx3, 0.160.1, 2026-10-09 —
#   à contre-relever à chaque montée de version].
EXTENDED_EFFORT_MODELS = {
    "claude-fable-5",
    "claude-fable-5-1",
    "claude-fable-5-2",
    "claude-opus-5",
    "claude-opus-5-5",
    "claude-sonnet-5",
    "claude-sonnet-5-5",
}

# Lettres = noms réels des CLI (décision opérateur, 2026-10-09) :
# L=low M=medium H=high X=xhigh MAX=max. Ultracode n'est plus un niveau
# (interrupteur séparé, claude uniquement) ; Ultra codex jamais proposé.
# Avant : L=medium M=high H=xhigh X=max U=ultracode — fichiers convertis par
# patch/migrate-effort-letters.py.
EFFORT_LEVELS_BASE = ("L", "M", "H")
EFFORT_LEVELS_EXTENDED = ("L", "M", "H", "X", "MAX")
EFFORT_DEFAULT = "H"


def private_tmpdir(cli, owner):
    """TMPDIR privé du moteur pour ce propriétaire, ou "" si sans objet."""
    import re
    template = ENGINE_PRIVATE_TMPDIR.get(cli)
    if not template or not owner or not re.fullmatch(_OWNER_RE, str(owner)):
        return ""
    return template.format(owner=owner)


def ultracode_supported(model_id):
    """Ultracode : interrupteur de session des modèles Claude 5 uniquement."""
    return (model_id or "") in EXTENDED_EFFORT_MODELS


def effort_levels_for_model(model_id):
    """Niveaux d'effort exposables pour un modèle donné."""
    model_id = model_id or ""
    if model_id in EXTENDED_EFFORT_MODELS or model_id.startswith(
            ENGINE_MODEL_PREFIX["codex"]):
        return list(EFFORT_LEVELS_EXTENDED)
    return list(EFFORT_LEVELS_BASE)


def engine_for_model(model_id):
    """Moteur déduit du modèle (gpt-* → codex, sinon claude).

    Miroir de engine_for_model (scripts/engines.sh) : le modèle est l'unique
    sélecteur de moteur exposé à l'utilisateur.
    """
    if model_id:
        for e, prefix in ENGINE_MODEL_PREFIX.items():
            if e != ENGINE_DEFAULT and model_id.startswith(prefix):
                return e
    return ENGINE_DEFAULT


def model_matches_engine(model_id, cli):
    """True si l'identifiant de modèle convient au moteur.

    Envoyer `/model gpt-5.6-sol` à Claude Code ne produit AUCUNE erreur : le TUI
    ignore la valeur inconnue et l'agent continue sur son modèle par défaut.
    D'où ce contrôle, appliqué à l'UI, à l'API et au démarrage.
    """
    prefix = ENGINE_MODEL_PREFIX.get(cli)
    return bool(prefix) and bool(model_id) and model_id.startswith(prefix)

# Sentinelle : valeur de marqueur NON ENCORE RELEVÉE sur le TUI réel.
# Sa présence fait échouer le chargement (fail-fast) : deviner un marqueur
# casserait la détection busy/ready sans aucune erreur visible.
TODO_SENTINEL = "__A_RENSEIGNER__"

# Sentinelle : signal qui N'EXISTE PAS dans ce TUI (≠ « pas encore relevé »).
# Autorisée, compilée en un motif qui ne matche jamais. Distinguer les deux est
# essentiel : « non relevé » est une dette, « non applicable » est un fait.
# Ex. : Codex n'affiche aucun marqueur de « compaction en cours » — il montre
# son indicateur d'activité normal, puis « Context compacted » à la fin.
NA_SENTINEL = "__NON_APPLICABLE__"

# Motif de remplacement d'un NA_SENTINEL : doit être inerte (ne jamais matcher)
# ET transportable dans argv. U+0001 (SOH) remplit les deux conditions :
# `tmux capture-pane -p` n'émet que du texte imprimable, et execve(2) n'interdit
# que l'octet nul. Une chaîne VIDE, elle, matcherait TOUS les panes.
NEVER_MATCH = "\x01__NEVER__\x01"

# Où chercher les busy_markers dans le pane :
#   'status_line' → uniquement dans la ligne de statut. Claude Code met l'indice
#                   « esc to interrupt » DANS la ligne « bypass permissions », et
#                   le prompt ❯ peut rester visible pendant que des sous-agents
#                   tournent : seule la ligne de statut fait foi.
#   'pane'        → n'importe où dans le pane. Codex affiche son indicateur
#                   d'activité « • Working (0s • esc to interrupt) » dans un
#                   widget SÉPARÉ, au-dessus du composer — et le composer « › »
#                   reste affiché pendant le travail. L'heuristique de Claude
#                   Code (« prompt visible = idle ») conclurait TOUJOURS idle.
BUSY_SCOPES = ("status_line", "pane")

# Même question pour l'indicateur de shells/terminaux en arrière-plan :
#   claude → « N bashes » est DANS la ligne de statut  → 'status_line'
#   codex  → « N background terminals running · /ps to view » est une ligne
#            distincte du footer                        → 'pane'
# Chercher `bashes_pattern` dans tout le pane côté claude ferait des faux
# positifs (le motif 'bashes|shell' matcherait n'importe quel texte).
BASHES_SCOPES = ("status_line", "pane")

# Clés obligatoires — tout fichier de marqueurs doit les fournir toutes.
REQUIRED_KEYS = (
    "process_names",
    "prompt_markers",
    "ready_markers",
    "busy_scope",
    "bashes_scope",
    "status_line",
    "runtime_model_pattern",
    "runtime_effort_pattern",
    "model_check_command",
    "effort_check_command",
    "model_check_history_pattern",
    "effort_check_history_pattern",
    "model_check_response_pattern",
    "effort_check_response_pattern",
    "busy_markers",
    "plan_mode",
    "compaction",
    "approval",
    "survey",
    "auto_response",
    "queued",
    "waiting_select",
    "context_limit",
    "model_change",
    "api_error",
    "scroll_indicator",
    "bashes_pattern",
    "context_pct_patterns",
    "api_error_patterns",
    "api_error_immediate_patterns",
    "login_expired_markers",
    "resume_hint_pattern",
    "resume_loading_markers",
    "exit_command",
    "status_command",
    "status_session_pattern",
    "status_dismiss_key",
)

_DIR = Path(__file__).resolve().parent


def current_engine():
    """Moteur actif pour ce process de bridge (AGENT_CLI, défaut `claude`)."""
    cli = os.environ.get("AGENT_CLI", "").strip() or ENGINE_DEFAULT
    if cli not in ENGINES:
        raise RuntimeError(
            f"[engines] Moteur inconnu : AGENT_CLI={cli!r}. "
            f"Moteurs supportés : {', '.join(ENGINES)}"
        )
    return cli


def markers_path(cli=None):
    """Chemin du fichier de marqueurs du moteur."""
    cli = cli or current_engine()
    return _DIR / f"markers.{cli}.yaml"


def _walk_values(node):
    """Aplatit récursivement toutes les valeurs scalaires d'un arbre YAML."""
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk_values(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _walk_values(v)
    else:
        yield node


def load_markers(cli=None):
    """Charge et valide les marqueurs du moteur. Fail-fast, jamais de fallback.

    Lève RuntimeError si : moteur inconnu, fichier absent, clé manquante,
    ou marqueur encore au sentinelle TODO.
    """
    cli = cli or current_engine()
    path = markers_path(cli)

    if not path.is_file():
        raise RuntimeError(
            f"[engines] Fichier de marqueurs introuvable : {path}\n"
            f"[engines] Le moteur `{cli}` ne peut pas être piloté sans ses marqueurs UI.\n"
            f"[engines] Les relever sur un TUI réel : "
            f"scripts/agent-bridge/capture-markers.sh {cli}"
        )

    with open(path, encoding="utf-8") as f:
        markers = yaml.safe_load(f) or {}

    missing = [k for k in REQUIRED_KEYS if k not in markers]
    if missing:
        raise RuntimeError(
            f"[engines] Clés manquantes dans {path.name} : {', '.join(missing)}"
        )

    todo = [
        k for k in markers
        if any(v == TODO_SENTINEL for v in _walk_values(markers[k]))
    ]
    if todo:
        raise RuntimeError(
            f"[engines] Marqueurs non renseignés dans {path.name} : {', '.join(sorted(todo))}\n"
            f"[engines] Ces chaînes sont propres au TUI de `{cli}` — elles ne peuvent pas\n"
            f"[engines] être devinées. Les relever sur une session réelle :\n"
            f"[engines]     scripts/agent-bridge/capture-markers.sh {cli}\n"
            f"[engines] puis remplacer chaque {TODO_SENTINEL} dans {path}."
        )

    for key, allowed in (("busy_scope", BUSY_SCOPES), ("bashes_scope", BASHES_SCOPES)):
        if markers[key] not in allowed:
            raise RuntimeError(
                f"[engines] {key} invalide dans {path.name} : "
                f"{markers[key]!r} (attendu : {', '.join(allowed)})"
            )

    return _substitute_na(markers)


def _substitute_na(node):
    """Remplace récursivement NA_SENTINEL par un motif qui ne matche jamais."""
    if isinstance(node, dict):
        return {k: _substitute_na(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute_na(v) for v in node]
    return NEVER_MATCH if node == NA_SENTINEL else node


def resume_session_ids(text, markers):
    """Identifiants de reprise imprimés par le CLI à sa sortie, dans l'ordre.

    `resume_hint_pattern` porte UN groupe capturant : l'identifiant. Le texte
    doit venir d'un `capture-pane -J`, sinon un UUID coupé par le retour à la
    ligne du pane ne matche pas. agent.sh compare le nombre d'identifiants
    avant et après la sortie : un ancien identifiant resté dans le scrollback
    ne doit jamais passer pour celui de la session qui vient de quitter.
    """
    pattern = markers["resume_hint_pattern"]
    if pattern == NEVER_MATCH:
        return []
    return re.findall(pattern, text)


def status_session_ids(text, markers):
    """Identifiants de session affichés par la commande de statut, dans l'ordre.

    `status_session_pattern` porte UN groupe capturant : l'identifiant, ancré
    sur son libellé (la fiche Codex affiche aussi l'UUID du workspace
    ChatGPT). Motif multiligne (`^` = début de ligne). Le texte doit venir
    d'un `capture-pane -J`.
    """
    pattern = markers["status_session_pattern"]
    if pattern == NEVER_MATCH:
        return []
    return re.findall(pattern, text, re.M)


# ═══════════════════════════════════════════════════════════════════════════
# Résolution du moteur d'un agent depuis la cascade .model.
# dans scripts/agent.sh.
# ═══════════════════════════════════════════════════════════════════════════

def resolve_agent_config(prompts_dir, agent_id, extension, default=""):
    """Resolve one agent config without trusting directory iteration order."""
    prompts_dir = Path(prompts_dir)
    base_id = agent_id.split("-")[0]
    directories = []
    exact = prompts_dir / base_id
    if exact.is_dir():
        directories.append(exact)
    directories.extend(sorted(
        path for path in prompts_dir.glob(f"{base_id}-*") if path.is_dir()
    ))
    matches = []
    for directory in directories:
        candidate = directory / f"{agent_id}.{extension}"
        if candidate.is_symlink() or candidate.exists():
            matches.append(candidate)
    if len(matches) > 1:
        raise RuntimeError(
            f"{agent_id}: multiple .{extension} overrides: "
            + ", ".join(str(path) for path in matches)
        )
    candidates = matches + [prompts_dir / f"{agent_id}.{extension}"]
    if "-" in agent_id:
        candidates.append(prompts_dir / f"{base_id}.{extension}")
    candidates.append(prompts_dir / f"default.{extension}")
    for candidate in candidates:
        if candidate.is_symlink() or candidate.exists():
            try:
                return candidate.read_text(encoding="utf-8").strip()
            except OSError:
                continue
    return default


def agent_engine(prompts_dir, agent_id):
    """Infer the engine from the effective model (the sole UI selector).

    Doit rester STRICTEMENT identique à resolve_engine() dans agent.sh : une
    divergence ferait parser un pane codex avec les marqueurs de Claude Code
    (agent vu figé ou mort au dashboard, sans erreur).
    """
    model_id = resolve_agent_config(prompts_dir, agent_id, "model")
    return engine_for_model(model_id) if model_id else ENGINE_DEFAULT


# ═══════════════════════════════════════════════════════════════════════════
# Génération du scan de pane bash (B6) depuis les marqueurs.
#
# Il existait TROIS implémentations du même parsing :
#   scripts/agent-bridge/agent.py       _parse_pane_state()  (marqueurs externalisés)
#   web/backend/multi_agent/cache.py    blob bash            (chaînes en dur)
#   scripts/debug-color.py              blob bash            (chaînes en dur)
# Les deux dernières étaient figées sur Claude Code. On les génère désormais
# depuis markers.<cli>.yaml — une seule source, testée par différentiel contre
# _parse_pane_state (cf. tests/test_pane_scan.py).
# ═══════════════════════════════════════════════════════════════════════════

def _q(s):
    """Échappement shell d'un littéral."""
    import shlex
    return shlex.quote(str(s))


def _bashes_block(markers):
    """Bloc bash de détection des shells en arrière-plan, selon bashes_scope."""
    src = '"$bp_line"' if markers["bashes_scope"] == "status_line" \
        else '"$(printf "%s" "$out" | tail -20)"'
    return (f'if printf "%s" {src} | grep -qE {_q(markers["bashes_pattern"])}; '
            'then has_bashes=1; fi; ')


def queued_markers(markers):
    """`queued` : chaîne ou liste de littéraux (le rendu change selon la version du CLI)."""
    raw = markers.get("queued")
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    return [str(x) for x in items if x]


def _busy_block(markers, busy_re):
    """Bloc bash de détection « occupé », selon busy_scope (cf. BUSY_SCOPES)."""
    if markers["busy_scope"] == "status_line":
        return (
            'if [ "$alive" -eq 0 ]; then busy=0; '
            f'elif printf "%s" "$bp_line" | grep -qE {_q(busy_re)}; then busy=1; '
            'elif [ -n "$bp_line" ]; then busy=0; '
            'else busy=1; fi; '
        )
    # 'pane' : l'indicateur d'activité est ailleurs que dans la ligne de statut,
    # et le composer reste visible pendant le travail → son absence seule fait foi.
    # Zone lue : les 20 dernières lignes ET, si `composer_prefix` est relevé, les
    # 20 lignes au-dessus de la dernière ligne qui commence par ce préfixe — un
    # brouillon long repousse l'indicateur hors des 20 dernières lignes.
    # Miroir exact de pane_busy_zone() (parité : tests/test_pane_scan.py).
    zone = '"$(printf "%s" "$out" | tail -20)"'
    prefix = markers.get("composer_prefix")
    if prefix:
        zone = (
            '"$(printf "%s" "$out" | awk -v p=' + _q(prefix) + ' '
            + "'{ a[NR]=$0; l=$0; sub(/^[[:space:]]+/, \"\", l); "
            "if (index(l, p) == 1) idx=NR } "
            "END { if (idx) { s=idx-" + str(BUSY_ZONE_LINES) + "; if (s<1) s=1; "
            "for (i=s; i<idx; i++) print a[i] } }'"
            '; printf "%s" "$out" | tail -' + str(BUSY_ZONE_LINES) + ')"'
        )
    # Une file de messages visible (n'importe où, en littéral) prouve aussi un
    # tour en cours : non bornée, elle repousse l'indicateur hors de toute
    # fenêtre fixe. Parité Python : agent._pane_scope_busy.
    queued_args = " ".join(f"-e {_q(q)}" for q in queued_markers(markers))
    queued_branch = (
        f'elif printf "%s" "$out" | grep -qF {queued_args}; then busy=1; '
        if queued_args else ''
    )
    return (
        'if [ "$alive" -eq 0 ]; then busy=0; '
        f'elif printf "%s" {zone} | grep -qE {_q(busy_re)}; then busy=1; '
        + queued_branch +
        'else busy=0; fi; '
    )


# Nombre de lignes lues pour l'indicateur « occupé » en portée 'pane' : les N
# dernières du pane, et les N au-dessus du composer quand il est ancré.
BUSY_ZONE_LINES = 20


def pane_busy_zone(lines, markers):
    """Lignes où chercher les busy_markers en portée 'pane' (miroir du bash).

    `lines` est le pane découpé sur '\\n'. Codex affiche « Working » juste
    au-dessus de son composer : un brouillon de plusieurs dizaines de lignes le
    repousse hors des 20 dernières lignes, et l'agent paraissait libre en plein
    travail. Le composer actif est la dernière ligne qui commence (après
    indentation) par `composer_prefix`.
    """
    zone = lines[-BUSY_ZONE_LINES:]
    prefix = markers.get("composer_prefix")
    if not prefix:
        return zone
    idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith(prefix):
            idx = i
    if idx is None:
        return zone
    return lines[max(0, idx - BUSY_ZONE_LINES):idx] + zone


ERROR_TAIL_LINES_DEFAULT = 20


def error_tail_lines(markers):
    """Nombre de lignes non vides, en bas du pane, où l'on cherche erreur API,
    session expirée et limite de contexte (`error_tail_lines` des marqueurs)."""
    n = int(markers.get("error_tail_lines", ERROR_TAIL_LINES_DEFAULT))
    if n < 1:
        raise ValueError(f"[engines] error_tail_lines doit être >= 1 (reçu {n})")
    return n


def build_pane_eval(markers):
    """Corps bash du parsing : lit $out, $pane_cmd, $id → écrit la ligne d'état.

    Contrat de sortie (14 champs, ordre historique — le consommateur cache.py
    les lit par position) :
      id:busy:compacted:ctx:done_compacting:prompt_loaded:ctx_limit:api_error
        :model_change:has_bashes:plan_mode:has_down:waiting_approval:login_required:alive
    """
    procs = "|".join(str(p) for p in markers["process_names"])
    busy_re = "|".join(str(b) for b in markers["busy_markers"])
    login_re = "|".join(str(x) for x in markers["login_expired_markers"])
    ctx_re = "|".join(str(p) for p in markers["context_pct_patterns"])
    api_error_re = "|".join(
        str(p) for p in markers["api_error_immediate_patterns"]
    )
    return (
        f'alive=0; case "$pane_cmd" in {procs}) alive=1;; esac; '
        'busy=0; has_bashes=0; has_down=0; plan_mode=0; compacted=0; ctx=-1; '
        'done_compacting=0; prompt_loaded=0; ctx_limit=0; api_error=0; model_change=0; '
        'waiting_approval=0; login_required=0; '
        f'bp_line=$(printf "%s" "$out" | grep -F {_q(markers["status_line"])} | tail -1); '
        # Erreur API, session expirée, limite de contexte : seules les lignes
        # du BAS font foi (mx81 2026-11-13 — un 403 Cloudflare de 9h47, résolu,
        # gardait 3 agents rouges des heures : panes de 2000 lignes, le scan
        # couvrait tout l'historique). Lignes vides finales ignorées, comme
        # _error_scope() côté Python.
        + f'err_scope=$(printf "%s" "$out" | awk -v n={error_tail_lines(markers)} '
        + "'{ l[NR]=$0 } /[^[:space:]]/ { last=NR } "
          "END { s=last-n+1; if (s<1) s=1; for (i=s; i<=last; i++) print l[i] }'); "
        + f'if printf "%s" "$err_scope" | grep -qiE {_q(login_re)}; then login_required=1; fi; '
        + _bashes_block(markers)
        + _busy_block(markers, busy_re) +
        'if [ "$login_required" -eq 1 ]; then busy=0; fi; '
        f'if printf "%s" "$bp_line" | grep -qF {_q(markers["scroll_indicator"])}; then has_down=1; fi; '
        f'plan_scope=$(printf "%s" "$out" | tail -{int(markers.get("plan_mode_tail_lines", 3))}); '
        f'if printf "%s" "$plan_scope" | awk -v marker={_q(markers["plan_mode"])} '
        + "'{ line=$0; sub(/^[[:space:]]+/, \"\", line); if (index(line, marker) == 1) print }'"
        + (f' | grep -F {_q(markers["plan_mode_required"])}'
           if markers.get('plan_mode_required') else '')
        + ''.join(f' | grep -vF {_q(x)}' for x in markers.get('plan_mode_exclusions', []))
        + ' | grep -q .; then plan_mode=1; fi; '
        f'if printf "%s" "$out" | grep -qF {_q(markers["waiting_select"])}; then waiting_approval=1; fi; '
        f'if printf "%s" "$out" | grep -qiF {_q(markers["compaction"]["in_progress"])}; then compacted=1; fi; '
        f'if printf "%s" "$out" | grep -qiF {_q(markers["compaction"]["done"])}; then done_compacting=1; fi; '
        'pid="${id%%-*}"; '
        'if [ "$done_compacting" -eq 1 ] && printf "%s" "$out" | '
        'grep -qE "prompts/${pid}[^ ]*/${id}[.-]|prompts/${id}-"; then prompt_loaded=1; fi; '
        f'pct=$(printf "%s" "$out" | grep -oE {_q(ctx_re)} | grep -oE "[0-9]+" | tail -1); '
        'if [ -n "$pct" ]; then ctx=$pct; fi; '
        f'if printf "%s" "$err_scope" | grep -qF {_q(markers["context_limit"])}; then ctx_limit=1; fi; '
        f'api_err_count=$(printf "%s" "$err_scope" | grep -cF {_q(markers["api_error"])} 2>/dev/null || echo 0); '
        f'if printf "%s" "$err_scope" | grep -qiE {_q(api_error_re)}; then api_error=1; fi; '
        'if [ "$api_err_count" -ge 3 ]; then api_error=1; fi; '
        'if [ "$alive" -eq 1 ] && [ -z "$bp_line" ]; then api_error=1; fi; '
        f'if printf "%s" "$out" | grep -qF {_q(markers["model_change"])}; then model_change=1; fi; '
        'echo "$id:$busy:$compacted:$ctx:$done_compacting:$prompt_loaded:$ctx_limit'
        ':$api_error:$model_change:$has_bashes:$plan_mode:$has_down:$waiting_approval:$login_required:$alive"; '
    )


def build_pane_scan(markers, ma_prefix="", capture_lines=30):
    """Script bash complet : capture les panes passés en argv, écrit une ligne
    d'état par agent. Un seul fork pour N agents (contrat de perf historique)."""
    return (
        'for s in "$@"; do '
        'id="${s#agent-}"; '
        f'out=$(tmux capture-pane -t "$s:0.0" -p -J -S -{capture_lines} 2>/dev/null); '
        'pane_cmd=$(tmux display-message -t "$s:0.0" -p "#{pane_current_command}" 2>/dev/null || echo ""); '
        + build_pane_eval(markers) +
        'done'
    )


PANE_FIELDS = (
    "id", "busy", "compacted", "context_pct", "done_compacting", "prompt_loaded",
    "context_limit", "api_error", "model_change", "has_bashes", "plan_mode",
    "has_down", "waiting_approval", "login_required", "claude_alive",
)


def rest_blockers(state, text, markers):
    """Raisons pour lesquelles l'agent n'est PAS au repos — vide = au repos.

    `state` : champs PANE_FIELDS du scan dashboard (build_pane_scan), donc la
    même lecture du pane que la couleur affichée. `text` : le pane visible,
    pour les marqueurs que le scan ne remonte pas (approbation, messages en
    file). Toute raison bloque `agent.sh update` : quitter le CLI pendant un
    tour, une question ou un menu perdrait le travail ou la réponse attendue.
    """
    reasons = []

    def add(reason):
        if reason not in reasons:
            reasons.append(reason)

    if not state.get("claude_alive"):
        add("cli_absent")
    if state.get("busy"):
        add("travaille")
    if state.get("has_bashes"):
        add("commandes_en_fond")
    if state.get("waiting_approval") or markers["approval"] in text:
        add("question")
    if state.get("plan_mode"):
        add("plan_mode")
    if state.get("compacted") and not state.get("done_compacting"):
        add("compaction")
    if any(q in text for q in queued_markers(markers)):
        add("messages_en_file")
    if state.get("login_required"):
        add("login")
    if state.get("context_limit") or state.get("api_error"):
        add("erreur")
    return reasons


def pane_state(session, markers, capture_lines=30):
    """État du pane 0 d'une session, par le script du dashboard. None si illisible."""
    script = build_pane_scan(markers, capture_lines=capture_lines)
    try:
        out = subprocess.run(["bash", "-c", script, "pane-state", session],
                             capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    lines = out.strip().splitlines()
    values = lines[-1].split(":") if lines else []
    if len(values) != len(PANE_FIELDS):
        return None
    state = dict(zip(PANE_FIELDS, values))
    for key in PANE_FIELDS:
        if key not in ("id", "context_pct"):
            state[key] = state[key] == "1"
    return state


def session_rest_blockers(session, markers, capture_lines=30):
    """rest_blockers() d'une session tmux réelle ; ['etat_illisible'] sinon."""
    state = pane_state(session, markers, capture_lines)
    if state is None:
        return ["etat_illisible"]
    try:
        text = subprocess.run(
            ["tmux", "capture-pane", "-t", f"{session}:0.0", "-p", "-J",
             "-S", f"-{capture_lines}"],
            capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return ["etat_illisible"]
    return rest_blockers(state, text, markers)


def profile_engine(profile):
    """Moteur déduit du nom d'un profil de login (claude1a → claude).

    Le répertoire login/<profil>/ n'a pas la même structure selon le moteur
    (CLAUDE_CONFIG_DIR vs CODEX_HOME) : le préfixe du nom porte l'information,
    sans introduire de 4e dimension de configuration.

    Retourne None si le profil ne correspond à aucun moteur connu — les
    appelants DOIVENT traiter ce cas (ne jamais présumer `claude`).
    """
    if not profile:
        return None
    for e in ENGINES:
        if profile.startswith(e):
            return e
    return None


# Nom de profil valide : <moteur><chiffre><lettre> — claude1a, codex2b…
PROFILE_RE = r"^(?:" + "|".join(ENGINES) + r")\d[a-z]$"


def is_valid_profile(profile):
    """True si <profile> est un nom de profil de login valide."""
    import re
    return bool(re.match(PROFILE_RE, profile or ""))


def _main(argv):
    """CLI minimale — permet à engines.sh de lire un marqueur sans dupliquer
    la logique de résolution du moteur ni le parsing YAML.

        python3 engines.py get ready_markers --cli codex
        python3 engines.py engine-of claude2b
        python3 engines.py profile-re
    """
    import argparse
    ap = argparse.ArgumentParser(prog="engines.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get", help="affiche un marqueur (une valeur par ligne)")
    g.add_argument("key")
    g.add_argument("--cli", default=None, choices=ENGINES)
    g.add_argument("--raw", action="store_true",
                   help="ne pas valider les sentinelles (diagnostic)")

    e = sub.add_parser("engine-of", help="moteur d'un profil de login")
    e.add_argument("profile")

    a2 = sub.add_parser("engine-of-agent", help="moteur d'un agent déduit du modèle")
    a2.add_argument("agent_id")
    a2.add_argument("--prompts", default=None, help="répertoire prompts/")

    sub.add_parser("profile-re", help="regex de nom de profil valide")
    sub.add_parser("list", help="liste des moteurs supportés")

    r = sub.add_parser("resume-ids",
                       help="identifiants de reprise lus sur stdin (capture-pane -J)")
    r.add_argument("--cli", default=None, choices=ENGINES)

    st = sub.add_parser("status-ids",
                        help="identifiants de session de la commande de statut, lus sur stdin")
    st.add_argument("--cli", default=None, choices=ENGINES)

    rb = sub.add_parser("rest-blockers",
                        help="raisons pour lesquelles l'agent n'est pas au repos")
    rb.add_argument("session")
    rb.add_argument("--cli", default=None, choices=ENGINES)

    a = ap.parse_args(argv)

    if a.cmd == "rest-blockers":
        for reason in session_rest_blockers(a.session,
                                            load_markers(a.cli or current_engine())):
            print(reason)
        return 0

    if a.cmd == "resume-ids":
        for session_id in resume_session_ids(sys.stdin.read(),
                                             load_markers(a.cli or current_engine())):
            print(session_id)
        return 0
    if a.cmd == "status-ids":
        for session_id in status_session_ids(sys.stdin.read(),
                                             load_markers(a.cli or current_engine())):
            print(session_id)
        return 0
    if a.cmd == "list":
        print(" ".join(ENGINES))
        return 0
    if a.cmd == "profile-re":
        print(PROFILE_RE)
        return 0
    if a.cmd == "engine-of-agent":
        prompts = Path(a.prompts) if a.prompts else _DIR.parent.parent / "prompts"
        print(agent_engine(prompts, a.agent_id))
        return 0
    if a.cmd == "engine-of":
        eng = profile_engine(a.profile)
        if eng is None:
            print(f"[engines] profil inconnu : {a.profile!r}", file=sys.stderr)
            return 1
        print(eng)
        return 0

    cli = a.cli or current_engine()
    if a.raw:
        with open(markers_path(cli), encoding="utf-8") as f:
            markers = yaml.safe_load(f) or {}
    else:
        markers = load_markers(cli)
    if a.key not in markers:
        print(f"[engines] clé inconnue : {a.key!r}", file=sys.stderr)
        return 1
    val = markers[a.key]
    for v in (val if isinstance(val, list) else [val]):
        print(v)
    return 0


if __name__ == "__main__":
    import sys
    try:
        sys.exit(_main(sys.argv[1:]))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
