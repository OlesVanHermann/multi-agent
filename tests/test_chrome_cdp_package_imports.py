"""
Tests EF-003b — Vérification des imports depuis le package cdp (refactoring/)

Après déploiement, le package sera dans scripts/cdp/. Ce fichier teste que :
1. Tous les symboles publics sont accessibles via le package __init__.py
2. Les imports par module individuel fonctionnent
3. Le wrapper de compatibilité (chrome_shared_wrapper.py) ré-exporte correctement
4. Les classes et constantes sont du bon type

Réf spec 342 : EF-003b (imports depuis scripts/cdp/), EF-005 (split modules)
CT-005 (wrapper compatibilité chrome-shared.py)
"""
import pytest
import os
import sys
import importlib
from unittest.mock import MagicMock, patch

# Add scripts/chrome_bridge/ to path (deployed structure)
_REFACTORING = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts', 'chrome_bridge'))
sys.path.insert(0, _REFACTORING)


# =============================================================================
# EF-003b — Imports depuis le package (__init__.py)
# =============================================================================

class TestPackageImports:
    """EF-003b — Le package __init__.py exporte tous les symboles publics"""

    EXPECTED_FUNCTIONS = [
        'get_agent_tab', 'set_agent_tab', 'del_agent_tab',
        'list_all_mappings', 'cleanup_stale_target',
        'get_my_agent_id', 'get_tabs', 'count_page_tabs',
        'create_tab', 'close_tab_by_id',
        'get_cdp', 'check_chrome_running', 'validate_target',
        'require_chrome_running',
    ]

    EXPECTED_CLASSES = ['CDP', 'CDPCommands']

    EXPECTED_CONSTANTS = [
        'REDIS_PREFIX', 'CHROME_PORT',
        'EXIT_OK', 'EXIT_ERROR', 'EXIT_CHROME_NOT_RUNNING',
        'EXIT_TARGET_STALE', 'EXIT_WEBSOCKET_FAILED',
        'MAX_IMAGE_DIM',
    ]

    def _import_package(self):
        """Import the refactoring package as a proper Python package (simulates `import cdp`)"""
        # Add parent of refactoring/ to path so Python resolves relative imports
        _parent = os.path.dirname(_REFACTORING)
        if _parent not in sys.path:
            sys.path.insert(0, _parent)
        # The package name is the directory name ('refactoring')
        pkg_name = os.path.basename(_REFACTORING)
        import importlib
        mod = importlib.import_module(pkg_name)
        return mod

    def test_all_functions_importable(self):
        """Toutes les fonctions publiques sont accessibles via le package (EF-003b)"""
        pkg = self._import_package()
        for name in self.EXPECTED_FUNCTIONS:
            assert hasattr(pkg, name), f"Missing export: {name}"
            assert callable(getattr(pkg, name)), f"{name} should be callable"

    def test_all_classes_importable(self):
        """Toutes les classes sont accessibles via le package (EF-003b)"""
        pkg = self._import_package()
        for name in self.EXPECTED_CLASSES:
            assert hasattr(pkg, name), f"Missing class export: {name}"
            obj = getattr(pkg, name)
            assert isinstance(obj, type), f"{name} should be a class"

    def test_all_constants_importable(self):
        """Toutes les constantes sont accessibles via le package (EF-003b)"""
        pkg = self._import_package()
        for name in self.EXPECTED_CONSTANTS:
            assert hasattr(pkg, name), f"Missing constant: {name}"

    def test_chrome_port_value(self):
        """CHROME_PORT est 9222 (CT-003, EF-003b)"""
        pkg = self._import_package()
        assert pkg.CHROME_PORT == 9222

    def test_exit_codes_are_integers(self):
        """Les codes de sortie sont des entiers (EF-003b)"""
        pkg = self._import_package()
        assert isinstance(pkg.EXIT_OK, int)
        assert isinstance(pkg.EXIT_ERROR, int)
        assert isinstance(pkg.EXIT_CHROME_NOT_RUNNING, int)
        assert pkg.EXIT_OK == 0
        assert pkg.EXIT_ERROR == 1

    def test_redis_prefix_format(self):
        """REDIS_PREFIX suit le format ma:chrome:tab: (CT-001, EF-003b)"""
        pkg = self._import_package()
        assert pkg.REDIS_PREFIX.startswith("ma:")
        assert "chrome" in pkg.REDIS_PREFIX


# =============================================================================
# EF-003b — Imports par module individuel
# =============================================================================

class TestIndividualModuleImports:
    """EF-003b — Chaque module est importable indépendamment"""

    def test_import_redis_integration(self):
        """redis_integration est importable directement (EF-003b)"""
        import redis_integration
        assert hasattr(redis_integration, 'get_agent_tab')
        assert hasattr(redis_integration, 'REDIS_PREFIX')

    def test_import_tab_manager(self):
        """tab_manager est importable directement (EF-003b)"""
        import tab_manager
        assert hasattr(tab_manager, 'get_tabs')
        assert hasattr(tab_manager, 'create_tab')

    def test_import_cdp_connection(self):
        """cdp_connection est importable directement (EF-003b)"""
        import cdp_connection
        assert hasattr(cdp_connection, 'CDP')
        assert hasattr(cdp_connection, 'CHROME_PORT')

    def test_import_cdp_commands(self):
        """cdp_commands est importable directement (EF-003b)"""
        import cdp_commands
        assert hasattr(cdp_commands, 'CDPCommands')
        assert hasattr(cdp_commands, 'MAX_IMAGE_DIM')


# =============================================================================
# CT-005 — Wrapper de compatibilité
# =============================================================================

class TestWrapperCompat:
    """CT-005 — Le wrapper chrome_shared_wrapper.py ré-exporte tout"""

    def test_wrapper_file_exists(self):
        """Le fichier wrapper existe dans refactoring/ (CT-005)"""
        wrapper_path = os.path.join(_REFACTORING, 'chrome_shared_wrapper.py')
        assert os.path.isfile(wrapper_path), "chrome_shared_wrapper.py not found"

    def test_wrapper_contains_deprecation_warning(self):
        """Le wrapper émet un DeprecationWarning (CT-005)"""
        wrapper_path = os.path.join(_REFACTORING, 'chrome_shared_wrapper.py')
        with open(wrapper_path) as f:
            content = f.read()
        assert 'DeprecationWarning' in content
        assert 'deprecated' in content.lower()

    def test_wrapper_exports_cdp_class(self):
        """Le wrapper exporte la classe CDP (CT-005)"""
        wrapper_path = os.path.join(_REFACTORING, 'chrome_shared_wrapper.py')
        with open(wrapper_path) as f:
            content = f.read()
        assert 'CDP' in content
        assert 'CDPCommands' in content

    def test_wrapper_exports_all_redis_functions(self):
        """Le wrapper exporte toutes les fonctions Redis (CT-005)"""
        wrapper_path = os.path.join(_REFACTORING, 'chrome_shared_wrapper.py')
        with open(wrapper_path) as f:
            content = f.read()
        for func in ['get_agent_tab', 'set_agent_tab', 'del_agent_tab',
                     'list_all_mappings', 'cleanup_stale_target']:
            assert func in content, f"Wrapper missing export: {func}"

    def test_wrapper_exports_tab_manager_functions(self):
        """Le wrapper exporte les fonctions tab_manager (CT-005)"""
        wrapper_path = os.path.join(_REFACTORING, 'chrome_shared_wrapper.py')
        with open(wrapper_path) as f:
            content = f.read()
        for func in ['get_my_agent_id', 'get_tabs', 'create_tab', 'close_tab_by_id']:
            assert func in content, f"Wrapper missing export: {func}"

    def test_wrapper_exports_connection_symbols(self):
        """Le wrapper exporte les symboles cdp_connection (CT-005)"""
        wrapper_path = os.path.join(_REFACTORING, 'chrome_shared_wrapper.py')
        with open(wrapper_path) as f:
            content = f.read()
        for sym in ['get_cdp', 'check_chrome_running', 'validate_target',
                    'CHROME_PORT', 'EXIT_OK', 'EXIT_ERROR']:
            assert sym in content, f"Wrapper missing export: {sym}"

    def test_wrapper_has_main(self):
        """Le wrapper a un point d'entrée main() (CT-005)"""
        wrapper_path = os.path.join(_REFACTORING, 'chrome_shared_wrapper.py')
        with open(wrapper_path) as f:
            content = f.read()
        assert 'def main()' in content
        assert '__main__' in content


# =============================================================================
# EF-003b — Cohérence croisée package ↔ chrome-shared.py original
# =============================================================================

class TestCrossConsistency:
    """EF-003b — Le package contient les mêmes symboles que l'original"""

    # Fonctions principales de chrome-shared.py original (2372 LOC)
    ORIGINAL_PUBLIC_SYMBOLS = [
        'get_my_agent_id', 'get_agent_tab', 'set_agent_tab', 'del_agent_tab',
        'get_tabs', 'count_page_tabs', 'check_chrome_running', 'validate_target',
        'cleanup_stale_target', 'require_chrome_running', 'create_tab',
        'close_tab_by_id', 'CDP', 'get_cdp',
        'CHROME_PORT', 'REDIS_PREFIX', 'MAX_IMAGE_DIM',
        'EXIT_OK', 'EXIT_ERROR', 'EXIT_CHROME_NOT_RUNNING',
        'EXIT_TARGET_STALE', 'EXIT_WEBSOCKET_FAILED',
    ]

    def test_package_covers_all_original_symbols(self):
        """Le package exporte TOUS les symboles publics de l'original (EF-003b)"""
        _parent = os.path.dirname(_REFACTORING)
        if _parent not in sys.path:
            sys.path.insert(0, _parent)
        pkg_name = os.path.basename(_REFACTORING)
        import importlib
        mod = importlib.import_module(pkg_name)

        missing = []
        for sym in self.ORIGINAL_PUBLIC_SYMBOLS:
            if not hasattr(mod, sym):
                missing.append(sym)

        assert not missing, f"Package missing symbols from original: {missing}"

    def test_cdp_class_has_core_methods(self):
        """La classe CDP a les méthodes CDP essentielles (EF-003b, EF-003a)"""
        from cdp_connection import CDP
        # CDP in cdp_connection is the low-level connection class
        # CDPCommands in cdp_commands has the high-level methods
        from cdp_commands import CDPCommands

        expected_methods = [
            'navigate', 'screenshot', 'click', 'evaluate',
            'get_html', 'type_text',
        ]
        for method in expected_methods:
            assert hasattr(CDPCommands, method), f"CDPCommands missing method: {method}"

    def test_cdp_commands_has_navigate_and_screenshot(self):
        """CDPCommands a les méthodes navigate et screenshot (EF-003b)"""
        from cdp_commands import CDPCommands
        assert hasattr(CDPCommands, 'navigate'), "CDPCommands missing navigate()"
        assert hasattr(CDPCommands, 'screenshot'), "CDPCommands missing screenshot()"
        assert callable(getattr(CDPCommands, 'navigate'))
        assert callable(getattr(CDPCommands, 'screenshot'))
