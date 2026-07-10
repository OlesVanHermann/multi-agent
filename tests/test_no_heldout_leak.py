"""
V3/C0 — Anti-fuite de l'oracle et du split held-out (plan §C0 : « held-out
jamais lu par 8XX/retrieval, vérifié par test »).

Double barrière de protection de l'oracle :
  1. permissions.deny des profils login/claude*/settings.json
     (Read+Write+Edit sur bench/oracle/**, Write+Edit sur pool-requests/tests/**)
  2. règles anti-hacking de verifier.py (FORBIDDEN_PATHS)
Ce module verrouille la barrière 1, la cohérence structurelle du banc
(chaque tâche a un oracle, le split est sain) et l'absence de toute
référence au contenu held-out dans les prompts/templates visibles agents.
"""
import glob
import json
import os
import re

import pytest

import verifier

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROFILES = sorted(glob.glob(os.path.join(BASE, "login", "claude*",
                                         "settings.json")))

ORACLE_DENY = ("Read(./bench/oracle/**)",
               "Write(./bench/oracle/**)",
               "Edit(./bench/oracle/**)")
POOL_TESTS_DENY = ("Write(./pool-requests/tests/**)",
                   "Edit(./pool-requests/tests/**)")


def _heldout_ids():
    with open(os.path.join(BASE, "bench", "heldout.txt"),
              encoding="utf-8") as f:
        return [line.strip() for line in f
                if line.strip() and not line.strip().startswith("#")]


def _all_task_ids():
    dirs = glob.glob(os.path.join(BASE, "bench", "tasks", "*", "*"))
    return sorted(os.path.basename(d) for d in dirs if os.path.isdir(d))


def _agent_visible_files():
    """Fichiers lus par les agents : prompts + templates (md/template/yaml)."""
    found = []
    for root in ("prompts", "templates"):
        for ext in ("*.md", "*.template", "*.yaml", "*.yml"):
            pattern = os.path.join(BASE, root, "**", ext)
            found.extend(glob.glob(pattern, recursive=True))
    return sorted(found)


class TestOracleDeny:
    def test_eight_profiles_present(self):
        assert len(PROFILES) == 8

    @pytest.mark.parametrize("profile", PROFILES,
                             ids=[p.split(os.sep)[-2] for p in PROFILES])
    def test_profile_denies_oracle_and_pool_tests(self, profile):
        with open(profile, encoding="utf-8") as f:
            deny = json.load(f)["permissions"]["deny"]
        for rule in ORACLE_DENY + POOL_TESTS_DENY:
            assert rule in deny, f"{profile}: règle manquante {rule}"

    def test_verifier_second_barrier(self):
        """Barrière 2 : verifier.py refuse tout diff touchant l'oracle."""
        assert any("bench/oracle" in p for p in verifier.FORBIDDEN_PATHS)
        assert any("pool-requests/tests" in p
                   for p in verifier.FORBIDDEN_PATHS)


class TestBenchStructure:
    def test_split_sain(self):
        heldout, all_ids = _heldout_ids(), _all_task_ids()
        assert heldout, "heldout.txt vide"
        assert set(heldout) <= set(all_ids), "held-out inconnu de tasks/"
        assert set(all_ids) - set(heldout), "split dev vide"

    @pytest.mark.parametrize("tid", _all_task_ids())
    def test_chaque_tache_a_son_oracle(self, tid):
        oracle = os.path.join(BASE, "bench", "oracle", tid, "verify.sh")
        assert os.path.isfile(oracle), f"oracle manquant pour {tid}"
        assert os.access(oracle, os.X_OK), f"{oracle} non exécutable"

    @pytest.mark.parametrize("tid", _all_task_ids())
    def test_chaque_tache_a_son_enonce(self, tid):
        matches = glob.glob(os.path.join(BASE, "bench", "tasks", "*",
                                         tid, "task.md"))
        assert len(matches) == 1

    def test_task_md_ne_mentionne_pas_l_oracle(self):
        """L'énoncé visible agent ne doit jamais pointer vers l'oracle."""
        for path in glob.glob(os.path.join(BASE, "bench", "tasks", "*", "*",
                                           "task.md")):
            with open(path, encoding="utf-8") as f:
                assert "bench/oracle" not in f.read(), path


class TestNoHeldoutLeak:
    def test_aucun_id_heldout_dans_prompts_ou_templates(self):
        heldout = _heldout_ids()
        for path in _agent_visible_files():
            with open(path, encoding="utf-8") as f:
                content = f.read()
            for tid in heldout:
                assert tid not in content, f"fuite held-out {tid} dans {path}"

    def test_aucun_chemin_profond_oracle_dans_prompts_ou_templates(self):
        """Mentionner `bench/oracle/` comme interdit (RULES.md §10) est
        légitime ; un chemin PROFOND (bench/oracle/<tid>/...) est une fuite."""
        deep = re.compile(r"bench/oracle/[A-Za-z0-9_]")
        for path in _agent_visible_files():
            with open(path, encoding="utf-8") as f:
                assert not deep.search(f.read()), f"chemin oracle dans {path}"
