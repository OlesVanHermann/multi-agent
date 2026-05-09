"""
Tests pour le script de migration backend (migrate_backend.py)
EF-007 — Validation que la migration fonctionne correctement

Réf spec 342 : CA-009 (docker-compose build OK), CT-005 (safe_rm uniquement)
"""
import pytest
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'migration'))


class TestCheckState:
    """EF-007 — Tests de la vérification pré-migration"""

    def test_check_detects_core_app(self, tmp_path):
        """check_state() détecte core/dashboard/app.py (EF-007)"""
        # Setup fake directory structure
        core_dir = tmp_path / "core" / "dashboard"
        core_dir.mkdir(parents=True)
        app_file = core_dir / "app.py"
        app_file.write_text("app = FastAPI()\n" * 50)

        web_dir = tmp_path / "web" / "backend"
        web_dir.mkdir(parents=True)

        dc_file = tmp_path / "web" / "docker-compose.yml"
        dc_file.write_text("services:\n  backend:\n    build: ./backend\n")

        from migrate_backend import check_state, CORE_APP, WEB_BACKEND
        with patch('migrate_backend.CORE_APP', app_file), \
             patch('migrate_backend.WEB_BACKEND', web_dir), \
             patch('migrate_backend.WEB_SERVER', web_dir / "server.py"), \
             patch('migrate_backend.DOCKER_COMPOSE', dc_file):
            state = check_state()

        assert state["core_app_exists"] is True
        assert state["core_app_loc"] == 50
        assert state["migration_needed"] is True

    def test_check_no_migration_needed(self, tmp_path):
        """check_state() détecte qu'aucune migration n'est nécessaire (EF-007)"""
        web_dir = tmp_path / "web" / "backend"
        web_dir.mkdir(parents=True)
        server = web_dir / "server.py"
        server.write_text("app = FastAPI()\n@app.get('/api/health')\ndef h(): pass\n")

        dc_file = tmp_path / "web" / "docker-compose.yml"
        dc_file.write_text("services:\n  backend:\n    build: ./backend\n")

        from migrate_backend import check_state
        with patch('migrate_backend.CORE_APP', tmp_path / "core" / "dashboard" / "app.py"), \
             patch('migrate_backend.WEB_BACKEND', web_dir), \
             patch('migrate_backend.WEB_SERVER', server), \
             patch('migrate_backend.DOCKER_COMPOSE', dc_file):
            state = check_state()

        assert state["core_app_exists"] is False
        assert state["migration_needed"] is False

    def test_check_detects_docker_compose_issue(self, tmp_path):
        """check_state() signale si docker-compose pointe vers core/ (EF-007)"""
        core_dir = tmp_path / "core" / "dashboard"
        core_dir.mkdir(parents=True)
        (core_dir / "app.py").write_text("app = FastAPI()\n")

        dc_file = tmp_path / "web" / "docker-compose.yml"
        dc_file.parent.mkdir(parents=True)
        dc_file.write_text("services:\n  backend:\n    build: ../core/dashboard\n")

        web_dir = tmp_path / "web" / "backend"
        web_dir.mkdir(parents=True)

        from migrate_backend import check_state
        with patch('migrate_backend.CORE_APP', core_dir / "app.py"), \
             patch('migrate_backend.WEB_BACKEND', web_dir), \
             patch('migrate_backend.WEB_SERVER', web_dir / "server.py"), \
             patch('migrate_backend.DOCKER_COMPOSE', dc_file):
            state = check_state()

        assert state["docker_compose_backend_path"] == "../core/dashboard"
        assert any("core/dashboard" in issue for issue in state["issues"])


class TestMigrate:
    """EF-007 — Tests de l'exécution de la migration"""

    def test_migrate_copies_to_web_backend(self, tmp_path):
        """migrate() copie app.py vers web/backend/ quand server.py absent (EF-007)"""
        core_dir = tmp_path / "core" / "dashboard"
        core_dir.mkdir(parents=True)
        (core_dir / "app.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n"
        )

        web_dir = tmp_path / "web" / "backend"
        web_dir.mkdir(parents=True)

        dc_file = tmp_path / "web" / "docker-compose.yml"
        dc_file.write_text("services:\n  backend:\n    build: ./backend\n")

        removed_dir = tmp_path / "removed"

        from migrate_backend import migrate
        with patch('migrate_backend.CORE_APP', core_dir / "app.py"), \
             patch('migrate_backend.WEB_BACKEND', web_dir), \
             patch('migrate_backend.WEB_SERVER', web_dir / "server.py"), \
             patch('migrate_backend.DOCKER_COMPOSE', dc_file), \
             patch('migrate_backend.REMOVED_DIR', removed_dir), \
             patch('migrate_backend.BASE_DIR', tmp_path):
            result = migrate()

        assert result is True
        # core/dashboard/app.py should be moved to removed/
        assert not (core_dir / "app.py").exists()
        assert removed_dir.exists()
        # web/backend/ should have the app
        backend_files = list(web_dir.glob("*.py"))
        assert len(backend_files) >= 1

    def test_migrate_adds_health_endpoint(self, tmp_path):
        """migrate() ajoute /api/health si absent (EF-007)"""
        core_dir = tmp_path / "core" / "dashboard"
        core_dir.mkdir(parents=True)
        (core_dir / "app.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n"
        )

        web_dir = tmp_path / "web" / "backend"
        web_dir.mkdir(parents=True)
        server = web_dir / "server.py"
        server.write_text("from fastapi import FastAPI\napp = FastAPI()\n")

        dc_file = tmp_path / "web" / "docker-compose.yml"
        dc_file.write_text("services:\n  backend:\n    build: ./backend\n")

        removed_dir = tmp_path / "removed"

        from migrate_backend import migrate
        with patch('migrate_backend.CORE_APP', core_dir / "app.py"), \
             patch('migrate_backend.WEB_BACKEND', web_dir), \
             patch('migrate_backend.WEB_SERVER', server), \
             patch('migrate_backend.DOCKER_COMPOSE', dc_file), \
             patch('migrate_backend.REMOVED_DIR', removed_dir), \
             patch('migrate_backend.BASE_DIR', tmp_path):
            migrate()

        with open(server) as f:
            content = f.read()
        assert "/api/health" in content

    def test_migrate_safe_rm(self, tmp_path):
        """migrate() utilise safe_rm (déplace vers removed/) (CT-005)"""
        core_dir = tmp_path / "core" / "dashboard"
        core_dir.mkdir(parents=True)
        (core_dir / "app.py").write_text("app = 1\n")

        web_dir = tmp_path / "web" / "backend"
        web_dir.mkdir(parents=True)
        (web_dir / "server.py").write_text("app = 2\n@app.get('/api/health')\ndef h(): pass\n")

        dc_file = tmp_path / "web" / "docker-compose.yml"
        dc_file.write_text("build: ./backend\n")

        removed_dir = tmp_path / "removed"

        from migrate_backend import migrate
        with patch('migrate_backend.CORE_APP', core_dir / "app.py"), \
             patch('migrate_backend.WEB_BACKEND', web_dir), \
             patch('migrate_backend.WEB_SERVER', web_dir / "server.py"), \
             patch('migrate_backend.DOCKER_COMPOSE', dc_file), \
             patch('migrate_backend.REMOVED_DIR', removed_dir), \
             patch('migrate_backend.BASE_DIR', tmp_path):
            migrate()

        # File should be in removed/, not deleted
        assert removed_dir.exists()
        removed_files = list(removed_dir.glob("*app.py"))
        assert len(removed_files) == 1

    def test_migrate_updates_docker_compose(self, tmp_path):
        """migrate() met à jour docker-compose.yml si nécessaire (EF-007)"""
        core_dir = tmp_path / "core" / "dashboard"
        core_dir.mkdir(parents=True)
        (core_dir / "app.py").write_text("app = 1\n")

        web_dir = tmp_path / "web" / "backend"
        web_dir.mkdir(parents=True)
        (web_dir / "server.py").write_text("@app.get('/api/health')\ndef h(): pass\n")

        dc_file = tmp_path / "web" / "docker-compose.yml"
        dc_file.write_text("services:\n  backend:\n    build: ../core/dashboard\n")

        removed_dir = tmp_path / "removed"

        from migrate_backend import migrate
        with patch('migrate_backend.CORE_APP', core_dir / "app.py"), \
             patch('migrate_backend.WEB_BACKEND', web_dir), \
             patch('migrate_backend.WEB_SERVER', web_dir / "server.py"), \
             patch('migrate_backend.DOCKER_COMPOSE', dc_file), \
             patch('migrate_backend.REMOVED_DIR', removed_dir), \
             patch('migrate_backend.BASE_DIR', tmp_path):
            migrate()

        with open(dc_file) as f:
            content = f.read()
        assert "../core/dashboard" not in content
        assert "./backend" in content


class TestVerify:
    """EF-007 — Tests de la vérification post-migration"""

    def test_verify_success(self, tmp_path):
        """verify() retourne True quand tout est OK (EF-007)"""
        web_dir = tmp_path / "web" / "backend"
        web_dir.mkdir(parents=True)
        server = web_dir / "server.py"
        server.write_text("app = FastAPI()\n@app.get('/api/health')\ndef h(): pass\n")

        dc_file = tmp_path / "web" / "docker-compose.yml"
        dc_file.write_text("services:\n  backend:\n    build: ./backend\n")

        from migrate_backend import verify
        with patch('migrate_backend.CORE_APP', tmp_path / "core" / "dashboard" / "app.py"), \
             patch('migrate_backend.WEB_BACKEND', web_dir), \
             patch('migrate_backend.DOCKER_COMPOSE', dc_file):
            result = verify()

        assert result is True

    def test_verify_fails_core_app_exists(self, tmp_path):
        """verify() échoue si core/dashboard/app.py existe encore (EF-007)"""
        core_dir = tmp_path / "core" / "dashboard"
        core_dir.mkdir(parents=True)
        (core_dir / "app.py").write_text("leftovers\n")

        web_dir = tmp_path / "web" / "backend"
        web_dir.mkdir(parents=True)
        (web_dir / "server.py").write_text("@app.get('/api/health')\ndef h(): pass\n")

        dc_file = tmp_path / "web" / "docker-compose.yml"
        dc_file.write_text("build: ./backend\n")

        from migrate_backend import verify
        with patch('migrate_backend.CORE_APP', core_dir / "app.py"), \
             patch('migrate_backend.WEB_BACKEND', web_dir), \
             patch('migrate_backend.DOCKER_COMPOSE', dc_file):
            result = verify()

        assert result is False
