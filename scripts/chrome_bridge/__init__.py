"""
chrome-bridge (anciennement chrome-shared) — Décomposition modulaire
EF-005 — Package regroupant les 4 modules du refactoring

Modules :
  - redis_integration : Mapping agent→tab dans Redis
  - cdp_connection    : Connexion WebSocket CDP + validation Chrome
  - tab_manager       : Création/fermeture d'onglets, identification agent
  - cdp_commands      : Commandes CDP de haut niveau (navigate, click, screenshot)

Ce __init__.py réexporte les symboles principaux pour la compatibilité.
"""

from .redis_integration import (
    get_agent_tab,
    set_agent_tab,
    del_agent_tab,
    list_all_mappings,
    cleanup_stale_target,
    REDIS_PREFIX,
)

from .tab_manager import (
    get_my_agent_id,
    get_tabs,
    count_page_tabs,
    create_tab,
    close_tab_by_id,
)

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

from .cdp_commands import CDPCommands, MAX_IMAGE_DIM
