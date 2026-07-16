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
        target = f"{cfg.MA_PREFIX}-agent-{agent_id}:0.0"
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
        session_name = f"{cfg.MA_PREFIX}-agent-{agent_id}"
        result = await _run_subprocess(["tmux", "has-session", "-t", session_name])
        return result.returncode == 0


_ANSI_RE = re.compile(r'\x1b(?:\[[0-9;]*[A-Za-z]|\].*?(?:\x07|\x1b\\)|\([A-Za-z0-9]|P.*?(?:\x1b\\))')


def _strip_ansi(text: str) -> str:
    """Remove ANSI/terminal escape codes from text."""
    return _ANSI_RE.sub('', text)


def _extract_current_input(ansi_output: str) -> str:
    """Extract typed input from tmux output captured with -e (ANSI codes).

    Distinguishes real typed text from Claude Code suggestions:
    - Suggestion: \\x1b[7m (reverse video = cursor) appears at position 0
      before any normal text. The cursor sitting at the start means nothing
      was typed, everything is ghost/suggestion text. Returns "".
    - Typed text: normal characters appear before any \\x1b[7m cursor.
      Returns only the typed portion (before suggestion/cursor escapes).

    Only searches the last 8 non-empty lines to avoid false prompt matches.
    """
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
