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
    "queued",
    "waiting_select",
    "context_limit",
    "model_change",
    "api_error",
    "scroll_indicator",
    "bashes_pattern",
    "context_pct_patterns",
    "api_error_patterns",
    "login_expired_markers",
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


# ═══════════════════════════════════════════════════════════════════════════
# Résolution du moteur d'un agent depuis la cascade .model.
# dans scripts/agent.sh.
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_agent_dir(prompts_dir, base_id):
    """Répertoire x45/z21 d'un agent : prompts/<id> ou prompts/<id>-<nom>."""
    import re
    exact = prompts_dir / base_id
    if exact.is_dir():
        return exact
    for d in prompts_dir.iterdir():
        if d.is_dir() and re.match(rf"^{re.escape(base_id)}-", d.name):
            return d
    return None


def agent_engine(prompts_dir, agent_id):
    """Infer the engine from the effective model (the sole UI selector).

    Doit rester STRICTEMENT identique à resolve_engine() dans agent.sh : une
    divergence ferait parser un pane codex avec les marqueurs de Claude Code
    (agent vu figé ou mort au dashboard, sans erreur).
    """
    prompts_dir = Path(prompts_dir)
    base_id = agent_id.split("-")[0]
    candidates = []
    agent_dir = _resolve_agent_dir(prompts_dir, base_id)
    if agent_dir is not None:
        candidates.append(agent_dir / f"{agent_id}.model")
    candidates.append(prompts_dir / f"{agent_id}.model")
    if "-" in agent_id:
        candidates.append(prompts_dir / f"{base_id}.model")
    candidates.append(prompts_dir / "default.model")
    for cand in candidates:
        if cand.is_symlink() or cand.exists():
            model_id = cand.read_text(encoding="utf-8").strip()
            return "codex" if model_id.startswith("gpt-") else "claude"
    return ENGINE_DEFAULT


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


def _busy_block(markers, busy_re, prompt0):
    """Bloc bash de détection « occupé », selon busy_scope (cf. BUSY_SCOPES)."""
    if markers["busy_scope"] == "status_line":
        return (
            'if [ "$alive" -eq 0 ]; then busy=0; '
            f'elif printf "%s" "$bp_line" | grep -qE {_q(busy_re)}; then busy=1; '
            f'elif printf "%s" "$out" | tail -10 | grep -qF {_q(prompt0)}; then busy=0; '
            'else busy=1; fi; '
        )
    # 'pane' : l'indicateur d'activité est ailleurs que dans la ligne de statut,
    # et le composer reste visible pendant le travail → son absence seule fait foi.
    return (
        'if [ "$alive" -eq 0 ]; then busy=0; '
        f'elif printf "%s" "$out" | tail -20 | grep -qE {_q(busy_re)}; then busy=1; '
        'else busy=0; fi; '
    )


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
    prompt0 = str(markers["prompt_markers"][0])

    return (
        f'alive=0; case "$pane_cmd" in {procs}) alive=1;; esac; '
        'busy=0; has_bashes=0; has_down=0; plan_mode=0; compacted=0; ctx=-1; '
        'done_compacting=0; prompt_loaded=0; ctx_limit=0; api_error=0; model_change=0; '
        'waiting_approval=0; login_required=0; '
        f'bp_line=$(printf "%s" "$out" | grep -F {_q(markers["status_line"])} | tail -1); '
        + f'if printf "%s" "$out" | grep -qiE {_q(login_re)}; then login_required=1; fi; '
        + _bashes_block(markers)
        + _busy_block(markers, busy_re, prompt0) +
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
        f'if printf "%s" "$out" | grep -qF {_q(markers["context_limit"])}; then ctx_limit=1; fi; '
        f'api_err_count=$(printf "%s" "$out" | grep -cF {_q(markers["api_error"])} 2>/dev/null || echo 0); '
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

    a = ap.parse_args(argv)

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
