"""Oracle s01-slugify. cwd = répertoire projet (bench_work/ dedans)."""
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "bench_work"))

from slugify import slugify


def test_exemples_enonce():
    assert slugify("Écran d'accueil") == "ecran-d-accueil"
    assert slugify("  Hello,  World!  ") == "hello-world"
    assert slugify("---") == ""


def test_accents_francais():
    assert slugify("àâçèéêëîïôùû") == "aaceeeeiiouu"


def test_minuscules():
    assert slugify("ABC") == "abc"


def test_sequences_non_alnum_fusionnees():
    assert slugify("a !? b") == "a-b"


def test_tirets_bords_supprimes():
    assert slugify("!a!") == "a"


def test_vide():
    assert slugify("") == ""


def test_chiffres_conserves():
    assert slugify("Version 2.12") == "version-2-12"
