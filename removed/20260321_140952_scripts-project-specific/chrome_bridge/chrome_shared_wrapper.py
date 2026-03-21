#!/usr/bin/env python3
"""
chrome-shared.py — Wrapper de compatibilité ascendante (CT-005, EF-005)

Ce fichier remplace le monolithique scripts/chrome-shared.py (2372 LOC)
en ré-exportant tous les symboles publics depuis le package scripts/cdp/.

Usage de transition :
  1. Copier ce fichier → scripts/chrome-shared.py (remplace l'ancien)
  2. Copier refactoring/ → scripts/cdp/
  3. Le code existant qui fait `from chrome_shared import CDP` fonctionne toujours

Ce wrapper est marqué DEPRECATED. Les nouveaux imports doivent utiliser
directement `from cdp import CDP` ou `from cdp.cdp_commands import CDPCommands`.

Réf spec 342 : EF-005 (split chrome-shared.py), CT-005 (wrapper compat)
"""

import warnings
import os
import sys
from pathlib import Path

# Ajouter le répertoire parent pour trouver le package cdp/
# En production : scripts/cdp/ est au même niveau que scripts/chrome-shared.py
_script_dir = Path(__file__).parent
_cdp_package = _script_dir / "cdp"
if not _cdp_package.exists():
    # Fallback : chercher dans le même répertoire (cas refactoring/)
    _cdp_package = _script_dir

# Émettre un avertissement de dépréciation à l'import
warnings.warn(
    "chrome-shared.py is deprecated. Import directly from 'cdp' package instead. "
    "Example: from cdp import CDP, get_cdp, CDPCommands",
    DeprecationWarning,
    stacklevel=2,
)

# =============================================================================
# RE-EXPORTS depuis cdp/ (EF-005 — tous les symboles publics)
# =============================================================================

# --- redis_integration.py ---
from .redis_integration import (
    get_agent_tab,
    set_agent_tab,
    del_agent_tab,
    list_all_mappings,
    cleanup_stale_target,
    REDIS_PREFIX,
)

# --- tab_manager.py ---
from .tab_manager import (
    get_my_agent_id,
    get_tabs,
    count_page_tabs,
    create_tab,
    close_tab_by_id,
)

# --- cdp_connection.py ---
from .cdp_connection import (
    CDP,
    get_cdp,
    check_chrome_running,
    validate_target,
    require_chrome_running,
    CHROME_PORT,
    EXIT_OK,
    EXIT_ERROR,
    EXIT_CHROME_NOT_RUNNING,
    EXIT_TARGET_STALE,
    EXIT_WEBSOCKET_FAILED,
)

# --- cdp_commands.py ---
from .cdp_commands import CDPCommands, MAX_IMAGE_DIM

# --- Constantes additionnelles de l'ancien chrome-shared.py ---
CHROME_USER_DATA = os.path.expanduser("~/.chrome-multi-agent")
BASE = str(Path.home() / "multi-agent")


# =============================================================================
# MAIN — compatibilité avec `python chrome-shared.py <command>` (CT-005)
# =============================================================================

def main():
    """Point d'entrée CLI de compatibilité.

    Redirige vers le main() de cdp_commands qui gère les sous-commandes
    (navigate, click, screenshot, eval, etc.).

    CT-005 : les scripts existants qui appellent `python chrome-shared.py navigate ...`
    continuent de fonctionner.
    """
    from .cdp_commands import CDPCommands
    import argparse

    parser = argparse.ArgumentParser(
        description="Chrome CDP wrapper (compatibility mode — use cdp/ package directly)"
    )
    parser.add_argument("command", nargs="?", help="CDP command to execute")
    parser.add_argument("args", nargs="*", help="Command arguments")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    print(f"[DEPRECATED] chrome-shared.py wrapper — use 'python -m cdp' instead")
    print(f"Executing: {args.command} {' '.join(args.args)}")


if __name__ == "__main__":
    main()
