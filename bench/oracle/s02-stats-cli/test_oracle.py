"""Oracle s02-stats-cli. cwd = répertoire projet (bench_work/ dedans)."""
import os
import subprocess
import sys

SCRIPT = os.path.join(os.getcwd(), "bench_work", "stats.py")


def _run(stdin_text):
    return subprocess.run([sys.executable, SCRIPT], input=stdin_text,
                          capture_output=True, text=True, timeout=30)


def test_exemple_enonce():
    res = _run("1\n2\n3\n4\n")
    assert res.returncode == 0
    assert res.stdout == "min=1.00\nmax=4.00\nmean=2.50\nmedian=2.50\n"


def test_valeur_unique():
    res = _run("5\n")
    assert res.returncode == 0
    assert res.stdout == "min=5.00\nmax=5.00\nmean=5.00\nmedian=5.00\n"


def test_decimaux_et_lignes_vides():
    res = _run("1.5\n\n2.5\n")
    assert res.returncode == 0
    assert "mean=2.00" in res.stdout


def test_mediane_nombre_pair():
    res = _run("1\n2\n3\n10\n")
    assert "median=2.50" in res.stdout


def test_ligne_invalide():
    res = _run("1\nabc\n")
    assert res.returncode == 2
    assert res.stdout == ""
    assert "ligne invalide" in res.stderr
    assert "abc" in res.stderr


def test_entree_vide():
    res = _run("")
    assert res.returncode == 1
    assert "aucune donnee" in res.stderr
