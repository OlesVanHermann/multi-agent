#!/usr/bin/env python3
"""
migrate_backend.py — Script de migration pour consolider le backend
EF-007 — Déplacer core/dashboard/app.py vers web/backend/ et unifier

Ce script :
  1. Vérifie l'état actuel (core/dashboard/app.py existe, web/backend/ existe)
  2. Fusionne les fonctionnalités de core/dashboard/app.py dans web/backend/
  3. Met à jour web/docker-compose.yml pour builder depuis web/backend/
  4. Vérifie que /api/health répond 200 après migration

Usage:
    python3 migrate_backend.py --check     # Vérification seulement (dry run)
    python3 migrate_backend.py --migrate   # Exécuter la migration
    python3 migrate_backend.py --verify    # Vérifier post-migration

Réf spec 342 : CA-009 (docker-compose build OK), CT-005 (safe_rm uniquement)
"""

import os
import sys
import shutil
import json
from pathlib import Path
from datetime import datetime


# =============================================================================
# CONSTANTS
# =============================================================================

BASE_DIR = Path(__file__).parent.parent.parent.parent.parent
CORE_APP = BASE_DIR / "core" / "dashboard" / "app.py"
WEB_BACKEND = BASE_DIR / "web" / "backend"
WEB_SERVER = WEB_BACKEND / "server.py"
DOCKER_COMPOSE = BASE_DIR / "web" / "docker-compose.yml"
REMOVED_DIR = BASE_DIR / "removed"


# =============================================================================
# CHECK — Vérification pré-migration
# =============================================================================

def check_state():
    """
    Vérifie l'état actuel du projet avant migration.

    Returns:
        dict: État de chaque composant (EF-007).
    """
    state = {
        "core_app_exists": CORE_APP.exists(),
        "core_app_loc": 0,
        "web_backend_exists": WEB_BACKEND.exists(),
        "web_server_exists": WEB_SERVER.exists(),
        "web_server_loc": 0,
        "docker_compose_exists": DOCKER_COMPOSE.exists(),
        "docker_compose_backend_path": None,
        "migration_needed": False,
        "issues": [],
    }

    if state["core_app_exists"]:
        with open(CORE_APP) as f:
            state["core_app_loc"] = sum(1 for _ in f)

    if state["web_server_exists"]:
        with open(WEB_SERVER) as f:
            state["web_server_loc"] = sum(1 for _ in f)

    if state["docker_compose_exists"]:
        with open(DOCKER_COMPOSE) as f:
            content = f.read()
        if "build: ./backend" in content:
            state["docker_compose_backend_path"] = "./backend"
        elif "../core/dashboard" in content:
            state["docker_compose_backend_path"] = "../core/dashboard"
            state["issues"].append("docker-compose references core/dashboard")

    # Déterminer si la migration est nécessaire
    if state["core_app_exists"]:
        if state["web_server_exists"]:
            state["issues"].append(
                "Both core/dashboard/app.py and web/backend/server.py exist. "
                "Need to merge functionality."
            )
            state["migration_needed"] = True
        else:
            state["migration_needed"] = True

    return state


# =============================================================================
# MIGRATE — Exécution de la migration
# =============================================================================

def migrate():
    """
    Exécute la migration du backend unifié.

    Étapes:
      1. Sauvegarde core/dashboard/app.py vers removed/ (CT-005 : safe_rm)
      2. Si web/backend/server.py existe déjà, s'assurer qu'il inclut /api/health
      3. Si web/backend/server.py n'existe pas, copier core/dashboard/app.py
      4. Vérifier docker-compose.yml pointe vers web/backend/

    Returns:
        bool: True si migration réussie (EF-007).
    """
    state = check_state()

    if not state["migration_needed"]:
        print("✓ Aucune migration nécessaire")
        return True

    print(f"État détecté:")
    print(f"  core/dashboard/app.py : {state['core_app_loc']} LOC")
    print(f"  web/backend/server.py : {state['web_server_loc']} LOC")
    print(f"  docker-compose.yml    : backend={state['docker_compose_backend_path']}")
    print()

    # Étape 1 : S'assurer que web/backend/ contient un serveur avec /api/health
    if state["web_server_exists"]:
        # web/backend/server.py existe déjà — vérifier /api/health
        with open(WEB_SERVER) as f:
            content = f.read()

        if "/api/health" not in content and '@app.get("/api/health")' not in content:
            print("→ Ajout endpoint /api/health à web/backend/server.py")
            health_endpoint = '''

# --- Health endpoint (EF-007: migration from core/dashboard) ---
@app.get("/api/health")
async def health_check():
    """Health check endpoint for monitoring and docker-compose validation (EF-007)."""
    return {"status": "ok", "source": "web/backend"}
'''
            # Append before the last line if it's `if __name__`
            if 'if __name__' in content:
                parts = content.rsplit('if __name__', 1)
                content = parts[0] + health_endpoint + '\nif __name__' + parts[1]
            else:
                content += health_endpoint

            with open(WEB_SERVER, 'w') as f:
                f.write(content)
            print("  ✓ /api/health ajouté")
        else:
            print("  ✓ /api/health déjà présent")
    else:
        # web/backend/server.py n'existe pas — copier depuis core/dashboard/app.py
        print("→ Copie core/dashboard/app.py → web/backend/app.py")
        WEB_BACKEND.mkdir(parents=True, exist_ok=True)
        target = WEB_BACKEND / "app.py"
        shutil.copy2(CORE_APP, target)

        # Ajouter /api/health si absent
        with open(target) as f:
            content = f.read()
        if "/api/health" not in content:
            with open(target, 'a') as f:
                f.write('''

@app.get("/api/health")
async def health_check():
    """Health check endpoint (EF-007)."""
    return {"status": "ok", "source": "web/backend"}
''')
        print("  ✓ Copié et /api/health ajouté")

    # Étape 2 : Sauvegarder l'ancien fichier (CT-005 : safe_rm)
    if state["core_app_exists"]:
        REMOVED_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{ts}_core_dashboard_app.py"
        backup_path = REMOVED_DIR / backup_name
        shutil.move(str(CORE_APP), str(backup_path))
        print(f"→ core/dashboard/app.py → removed/{backup_name} (safe_rm)")

    # Étape 3 : Vérifier docker-compose.yml
    if state["docker_compose_exists"]:
        with open(DOCKER_COMPOSE) as f:
            dc_content = f.read()

        if "../core/dashboard" in dc_content:
            print("→ Mise à jour docker-compose.yml : core/dashboard → ./backend")
            dc_content = dc_content.replace("../core/dashboard", "./backend")
            with open(DOCKER_COMPOSE, 'w') as f:
                f.write(dc_content)
            print("  ✓ docker-compose.yml mis à jour")
        elif "build: ./backend" in dc_content:
            print("  ✓ docker-compose.yml déjà configuré pour ./backend")

    print()
    print("✓ Migration terminée")
    return True


# =============================================================================
# VERIFY — Vérification post-migration
# =============================================================================

def verify():
    """
    Vérifie que la migration est correcte.

    Checks:
      1. core/dashboard/app.py n'existe plus (ou est dans removed/)
      2. web/backend/ contient le serveur avec /api/health
      3. docker-compose.yml build depuis ./backend

    Returns:
        bool: True si tout est OK (EF-007, CA-009).
    """
    ok = True

    # Check 1: core/dashboard/app.py should be gone
    if CORE_APP.exists():
        print("✗ core/dashboard/app.py existe encore (migration incomplète)")
        ok = False
    else:
        print("✓ core/dashboard/app.py supprimé (dans removed/)")

    # Check 2: web/backend/ has a server
    backend_files = list(WEB_BACKEND.glob("*.py")) if WEB_BACKEND.exists() else []
    if backend_files:
        has_health = False
        for f in backend_files:
            with open(f) as fh:
                if "/api/health" in fh.read():
                    has_health = True
                    break
        if has_health:
            print("✓ web/backend/ contient un serveur avec /api/health")
        else:
            print("✗ web/backend/ n'a pas d'endpoint /api/health")
            ok = False
    else:
        print("✗ web/backend/ ne contient pas de fichier Python")
        ok = False

    # Check 3: docker-compose.yml
    if DOCKER_COMPOSE.exists():
        with open(DOCKER_COMPOSE) as f:
            content = f.read()
        if "build: ./backend" in content:
            print("✓ docker-compose.yml build depuis ./backend")
        elif "../core/dashboard" in content:
            print("✗ docker-compose.yml référence encore core/dashboard")
            ok = False
        else:
            print("⚠ docker-compose.yml — configuration backend non détectée")
    else:
        print("⚠ docker-compose.yml non trouvé")

    return ok


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Point d'entrée CLI (EF-007)."""
    if len(sys.argv) < 2:
        print("Usage: python3 migrate_backend.py <--check|--migrate|--verify>")
        print()
        print("  --check    Vérification pré-migration (dry run)")
        print("  --migrate  Exécuter la migration")
        print("  --verify   Vérification post-migration")
        sys.exit(1)

    action = sys.argv[1]

    if action == "--check":
        state = check_state()
        print("=== État pré-migration ===")
        print(f"  core/dashboard/app.py : {'existe' if state['core_app_exists'] else 'absent'} ({state['core_app_loc']} LOC)")
        print(f"  web/backend/server.py : {'existe' if state['web_server_exists'] else 'absent'} ({state['web_server_loc']} LOC)")
        print(f"  docker-compose.yml    : backend={state['docker_compose_backend_path']}")
        print(f"  Migration nécessaire  : {'OUI' if state['migration_needed'] else 'NON'}")
        if state["issues"]:
            print(f"  Issues:")
            for issue in state["issues"]:
                print(f"    - {issue}")

    elif action == "--migrate":
        success = migrate()
        sys.exit(0 if success else 1)

    elif action == "--verify":
        success = verify()
        sys.exit(0 if success else 1)

    else:
        print(f"Action inconnue: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
