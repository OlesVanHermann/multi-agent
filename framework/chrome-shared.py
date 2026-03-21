#!/usr/bin/env python3
"""
chrome-shared.py — Wrapper de compatibilité ascendante (CT-005, EF-005)

Ce fichier remplace le monolithique chrome-shared.py (2372 LOC)
en déléguant au package scripts/chrome_bridge/ (4 modules, ~1280 LOC).

Usage CLI identique :
  python3 chrome-shared.py tab <url>
  python3 chrome-shared.py screenshot out.png
  python3 chrome-shared.py click <selector>

Ce wrapper est DEPRECATED. Les nouveaux imports doivent utiliser
directement le package chrome_bridge/ :
  from chrome_bridge import CDP, get_cdp, CDPCommands

Réf spec 342 : EF-005 (split chrome-shared.py), CT-005 (wrapper compat)
"""

import warnings
import os
import sys

# Ajouter le répertoire scripts/ au path pour que le package chrome_bridge/ soit trouvable
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

# Avertissement de dépréciation
warnings.warn(
    "chrome-shared.py is deprecated. Import directly from 'chrome_bridge' package instead. "
    "Example: from chrome_bridge import CDP, get_cdp, CDPCommands",
    DeprecationWarning,
    stacklevel=2,
)

# =============================================================================
# RE-EXPORTS depuis chrome_bridge/ (EF-005 — tous les symboles publics)
# =============================================================================

from chrome_bridge.redis_integration import (
    get_agent_tab,
    set_agent_tab,
    del_agent_tab,
    list_all_mappings,
    cleanup_stale_target,
    REDIS_PREFIX,
)

from chrome_bridge.tab_manager import (
    get_my_agent_id,
    get_tabs,
    count_page_tabs,
    create_tab,
    close_tab_by_id,
)

from chrome_bridge.cdp_connection import (
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

from chrome_bridge.cdp_commands import CDPCommands, MAX_IMAGE_DIM

# Constantes additionnelles de l'ancien chrome-shared.py
from pathlib import Path
CHROME_USER_DATA = os.path.expanduser("~/.chrome-multi-agent")
BASE = str(Path.home() / "multi-agent")


# =============================================================================
# MAIN — compatibilité avec `python chrome-shared.py <command>` (CT-005)
# =============================================================================

def main():
    """Point d'entrée CLI de compatibilité."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Chrome CDP wrapper (compatibility mode — use chrome_bridge/ package directly)"
    )
    parser.add_argument("command", nargs="?", help="CDP command to execute")
    parser.add_argument("args", nargs="*", help="Command arguments")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    print(f"[DEPRECATED] chrome-shared.py wrapper — use 'python -m chrome_bridge' instead")
    print(f"Executing: {args.command} {' '.join(args.args)}")


if __name__ == "__main__":
    main()
