"""
A6 — Centralisation de la regex de validation d'ID agent

Source unique Python : scripts/agent-bridge/ids.py
Source unique shell  : scripts/lib.sh
"""
import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.realpath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
sys.path.insert(0, os.path.join(_REPO_ROOT, 'scripts', 'agent-bridge'))

VALID = ["000", "300", "999", "345-500", "000-000", "999-999"]
INVALID = [
    "", "30", "3000", "300-", "-300", "300-5000", "300-50",
    "abc", "3a0", "300 ", " 300", "300\n301",
    "300; rm -rf /", "300`id`", "300$(reboot)", "300|cat",
    "300-500-600", "../300", "300/..",
]


class TestPythonSource:
    def test_valid_ids(self):
        from ids import is_valid_agent_id
        for v in VALID:
            assert is_valid_agent_id(v), v

    def test_invalid_ids(self):
        from ids import is_valid_agent_id
        for v in INVALID:
            assert not is_valid_agent_id(v), repr(v)

    def test_pattern_composable(self):
        """Le pattern brut (sans ancres) se compose dans des regex plus larges."""
        import re
        from ids import AGENT_ID_PATTERN
        m = re.match(rf'^({AGENT_ID_PATTERN})_(\d+)\.prompt$', "345-500_2.prompt")
        assert m and m.group(1) == "345-500" and m.group(2) == "2"

    def test_consumers_import_single_source(self):
        """agent.py, healthcheck.py et server.py utilisent ids.py."""
        for rel in ('scripts/agent-bridge/agent.py',
                    'scripts/agent-bridge/healthcheck.py',
                    'web/backend/server.py'):
            src = open(os.path.join(_REPO_ROOT, rel), encoding='utf-8').read()
            assert 'from ids import' in src, rel

    def test_no_inline_pattern_outside_source(self):
        """Le littéral du pattern ne subsiste que dans ids.py et lib.sh."""
        for root in ('scripts', 'web'):
            for dirpath, _dirs, files in os.walk(os.path.join(_REPO_ROOT, root)):
                if '__pycache__' in dirpath or 'node_modules' in dirpath:
                    continue
                for fname in files:
                    if not fname.endswith(('.py', '.sh')):
                        continue
                    path = os.path.join(dirpath, fname)
                    if fname in ('ids.py', 'lib.sh'):
                        continue
                    content = open(path, encoding='utf-8', errors='replace').read()
                    assert '0-9]{3}' not in content, f"pattern en dur dans {path}"


class TestShellSource:
    def _check(self, agent_id):
        lib = os.path.join(_REPO_ROOT, 'scripts', 'lib.sh')
        r = subprocess.run(
            ['bash', '-c', f'source "$1"; is_valid_agent_id "$2"', '_', lib, agent_id],
            capture_output=True)
        return r.returncode == 0

    def test_valid_ids(self):
        for v in VALID:
            assert self._check(v), v

    def test_invalid_ids(self):
        for v in INVALID:
            assert not self._check(v), repr(v)
