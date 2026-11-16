"""Accès tmux/SSH : exécuteur dédié, capture de panes, parsing terminal (B1)."""

import os
import asyncio
import concurrent.futures
import re
import socket
import subprocess

from . import config as cfg

# Dedicated thread pool for subprocess calls (tmux).
# Default asyncio pool is only 20 threads — easily saturated by WS handlers
# each doing 2x subprocess.run per tick. 64 threads handles up to ~30 concurrent
# WS connections without starvation.
_tmux_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=64, thread_name_prefix="tmux"
)


async def _run_subprocess(cmd, **kwargs):
    """Run subprocess in dedicated thread pool. Never blocks the asyncio default pool."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("timeout", 5)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _tmux_executor, lambda: subprocess.run(cmd, **kwargs)
    )


def _tmux_socket_path() -> str:
    """Chemin du socket du serveur tmux par défaut (TMUX_TMPDIR/tmux-<uid>/default)."""
    tmpdir = os.environ.get("TMUX_TMPDIR", "/tmp")
    return os.path.join(tmpdir, f"tmux-{os.getuid()}", "default")


async def _tmux_server_alive() -> bool:
    """True si le serveur tmux tourne déjà.

    Le backend tourne dans un sandbox systemd (ProtectHome=read-only) : s'il
    est le premier client tmux, le serveur naîtrait DANS ce namespace et
    toutes les sessions futures (agents, keepalive) hériteraient d'un /home
    en lecture seule — Claude/Codex démarrent puis échouent sur la moindre
    écriture. Toute création de session depuis le backend doit donc être
    refusée tant qu'un serveur sain (démarré depuis un shell : infra.sh,
    agent.sh, scheduler) n'existe pas.

    SANS INVOQUER tmux : TOUTE commande tmux (y compris `has-session`) crée
    le socket ET le serveur — une garde à base de has-session déclenche
    elle-même l'empoisonnement qu'elle doit empêcher (vécu : infra.sh stop →
    auto-restart systemd → premier tick → serveur né sandboxé → EROFS).
    On teste le SOCKET, sans effet de bord.
    """
    path = _tmux_socket_path()
    if not os.path.exists(path):
        return False
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(0.25)
    try:
        probe.connect(path)
        return True
    except OSError:
        return False
    finally:
        probe.close()


TMUX_SERVER_ABSENT_DETAIL = (
    "serveur tmux absent — refus de le créer depuis le backend sandboxé "
    "(/home serait monté en lecture seule pour toutes les sessions). "
    "Démarrer d'abord le scheduler ou un agent depuis un shell : "
    "./scripts/infra.sh start ou ./scripts/agent.sh start <id>."
)


def _get_remote_info(agent_id: str):
    """Return (ssh_cmd, remote_session) for remote agents, or None for local ones.

    A remote agent has prompts/<dir>/<agent_id>.remote + prompts/<dir>/remote.ssh.
    The dashboard should SSH-capture the remote tmux pane directly instead of
    capturing the local wrapper pane (which only has ~pane_height lines).
    """
    prompts_dir = cfg.BASE_DIR / "prompts"
    if not prompts_dir.is_dir():
        return None
    for d in prompts_dir.iterdir():
        if not d.is_dir():
            continue
        remote_file = d / f"{agent_id}.remote"
        if not remote_file.exists():
            continue
        ssh_file = d / "remote.ssh"
        if not ssh_file.exists():
            return None
        try:
            ssh_cmd = ssh_file.read_text().strip()
            remote_session = remote_file.read_text().strip()
        except Exception:
            return None
        if not ssh_cmd or not remote_session:
            return None
        if not ssh_cmd.startswith("ssh "):
            return None
        if not re.match(r'^[A-Za-z0-9@._:/ -]+$', ssh_cmd):
            return None
        if not re.match(r'^[A-Za-z0-9_.-]+$', remote_session):
            return None
        return (ssh_cmd, remote_session)
    return None


async def _capture_agent_pane(agent_id: str, lines: int = 500, ansi: bool = False):
    """Capture pane output for an agent, transparently handling remote agents via SSH.

    For remote agents, runs tmux capture-pane on the REMOTE host via SSH so we get
    the full scrollback, not just the local wrapper pane's visible rows.
    Returns a subprocess.CompletedProcess-like result with .returncode and .stdout.
    """
    remote = _get_remote_info(agent_id)
    if remote:
        ssh_cmd, remote_session = remote
        target = f"{remote_session}:0.0"
        if ansi:
            inner = f"tmux capture-pane -t {target} -p -e -S -20"
        else:
            inner = f"tmux capture-pane -t {target} -p -J -S -{lines}"
        import shlex
        ssh_args = shlex.split(ssh_cmd)
        args = ssh_args + ["-o", "ConnectTimeout=5", inner]
        return await _run_subprocess(args, text=True)
    else:
        target = f"agent-{agent_id}:0.0"
        if ansi:
            args = ["tmux", "capture-pane", "-t", target, "-p", "-e", "-S", "-20"]
        else:
            args = ["tmux", "capture-pane", "-t", target, "-p", "-J", "-S", f"-{lines}"]
        return await _run_subprocess(args, text=True)


async def _agent_session_exists(agent_id: str) -> bool:
    """Check whether the agent's tmux session exists (locally or on remote host)."""
    remote = _get_remote_info(agent_id)
    if remote:
        ssh_cmd, remote_session = remote
        import shlex
        ssh_args = shlex.split(ssh_cmd)
        args = ssh_args + ["-o", "ConnectTimeout=5", f"tmux has-session -t {remote_session}"]
        result = await _run_subprocess(args)
        return result.returncode == 0
    else:
        session_name = f"agent-{agent_id}"
        result = await _run_subprocess(["tmux", "has-session", "-t", session_name])
        return result.returncode == 0


_ANSI_RE = re.compile(r'\x1b(?:\[[0-9;]*[A-Za-z]|\].*?(?:\x07|\x1b\\)|\([A-Za-z0-9]|P.*?(?:\x1b\\))')


def _strip_ansi(text: str) -> str:
    """Remove ANSI/terminal escape codes from text."""
    return _ANSI_RE.sub('', text)


def _engine_composer_prefixes() -> tuple:
    """Préfixes de composer relevés dans markers.<cli>.yaml (clé optionnelle).

    Claude Code n'en déclare pas : son « ❯ » reste lu par la logique historique
    ci-dessous. Codex déclare « › ».
    """
    import engines  # cfg a inséré scripts/agent-bridge dans sys.path

    prefixes = []
    for cli in engines.ENGINES:
        try:
            prefix = engines.load_markers(cli).get("composer_prefix")
        except RuntimeError:
            continue  # moteur aux marqueurs non relevés : rien à lire
        if prefix and prefix != engines.NEVER_MATCH:
            prefixes.append(prefix)
    return tuple(prefixes)


_COMPOSER_PREFIXES = _engine_composer_prefixes()

_SGR_RE = re.compile(r'\x1b\[([0-9;]*)m')


def _sgr_dim_state(text: str, dim: bool = False) -> bool:
    """État « grisé » (SGR 2) après les séquences SGR de `text`.

    `22` et `0` (ou `ESC[m`) l'annulent ; les couleurs étendues 38/48/58
    (`;5;n` ou `;2;r;g;b`) sont sautées pour qu'une couleur 2 ne passe pas
    pour du grisé.
    """
    for m in _SGR_RE.finditer(text):
        params = m.group(1).split(";") if m.group(1) else ["0"]
        i = 0
        while i < len(params):
            code = params[i] or "0"
            if code in ("38", "48", "58") and i + 1 < len(params):
                i += {"5": 3, "2": 5}.get(params[i + 1], 1)
                continue
            if code in ("0", "22"):
                dim = False
            elif code == "2":
                dim = True
            i += 1
    return dim


def _extract_prefixed_composer(ansi_output: str, prefix: str):
    """Texte du composer d'un TUI dont la 1re ligne commence par `prefix` (Codex).

    Retourne None si le bas du pane ne porte pas ce composer, "" s'il est vide
    ou inactif, sinon le texte saisi. Le composer actif est la dernière ligne
    NON indentée du pane : ses lignes de continuation et le footer sont
    indentés. Un « › » grisé (SGR 2) est un ancien message de l'historique, un
    texte grisé après le préfixe est le texte d'aide. Une option numérotée
    (« › 1. Yes ») est un dialogue, pas un composer.

    Limite : Codex replie lui-même les lignes ; elles sont rejointes par une
    espace, ce qui est exact sauf pour un mot coupé en fin de ligne.
    """
    lines = ansi_output.rstrip("\n").split("\n")
    start = None
    for i in range(len(lines) - 1, -1, -1):
        clean = _strip_ansi(lines[i])
        if not clean.strip() or clean[:1].isspace():
            continue
        if clean.startswith(prefix):
            start = i
        break
    if start is None:
        return None

    raw = lines[start]
    pos = raw.find(prefix)
    prefix_dim = _sgr_dim_state(raw[:pos])
    if prefix_dim:
        return ""
    after = raw[pos + len(prefix):]
    lead = re.match(r'(?:\x1b\[[0-9;]*m| )*', after).group(0)
    if _sgr_dim_state(lead, prefix_dim):
        return ""
    first = _strip_ansi(after).strip()
    if re.match(r'^[0-9]+[.):]\s', first):
        return ""

    parts = [first] if first else []
    for line in lines[start + 1:]:
        clean = _strip_ansi(line).strip()
        if not clean:
            break
        parts.append(clean)
    return " ".join(parts)


def _extract_current_input(ansi_output: str) -> str:
    """Extract typed input from tmux output captured with -e (ANSI codes).

    Codex (préfixe de composer déclaré dans markers.<cli>.yaml) est lu en
    premier par _extract_prefixed_composer ; sans cela le dashboard croyait
    son composer toujours vide.

    Distinguishes real typed text from Claude Code suggestions:
    - Suggestion: \\x1b[7m (reverse video = cursor) appears at position 0
      before any normal text. The cursor sitting at the start means nothing
      was typed, everything is ghost/suggestion text. Returns "".
    - Typed text: normal characters appear before any \\x1b[7m cursor.
      Returns only the typed portion (before suggestion/cursor escapes).

    Only searches the last 8 non-empty lines to avoid false prompt matches.
    """
    for prefix in _COMPOSER_PREFIXES:
        typed = _extract_prefixed_composer(ansi_output, prefix)
        if typed is not None:
            return typed

    SKIP_MARKERS = ["⏵", "───"]

    lines = ansi_output.rstrip().split("\n")
    checked = 0

    for line in reversed(lines):
        clean = _strip_ansi(line).strip()
        if not clean:
            continue
        if any(m in clean for m in SKIP_MARKERS) or clean.startswith("⏺"):
            continue

        checked += 1
        if checked > 8:
            break

        # Look for ❯ prompt (with or without ANSI around it)
        prompt_match = re.search(r'❯[\xa0 ]', line)
        if prompt_match:
            after = line[prompt_match.end():]

            # Check if \x1b[7m (cursor/reverse video) appears before any normal text.
            # Pattern: optional ANSI codes, then \x1b[7m → cursor at pos 0 → all suggestion
            if re.match(r'(?:\x1b\[[0-9;]*m)*\x1b\[7m', after):
                return ""

            # Real text exists before cursor. Extract up to first suggestion marker:
            # \x1b[7m (cursor), \x1b[2m (dim), \x1b[0;2m (reset+dim)
            sugg_start = re.search(r'\x1b\[(?:7m|2m|0;2m)', after)
            if sugg_start:
                typed_part = after[:sugg_start.start()]
            else:
                typed_part = after

            return _strip_ansi(typed_part).strip()

        # Fallback: other prompt types (no suggestion detection)
        for prompt in ["$ ", ">>> ", "... ", "> "]:
            if prompt in clean:
                idx = clean.rfind(prompt)
                return clean[idx + len(prompt):]

    return ""
