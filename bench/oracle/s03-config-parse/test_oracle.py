"""Oracle s03-config-parse. cwd = répertoire projet (bench_work/ dedans)."""
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "bench_work"))

import pytest

from config_parse import parse_config


def test_exemple_enonce():
    text = ("# global\n"
            "timeout = 30\n"
            "\n"
            "[redis]\n"
            "host = localhost\n"
            "port = 6379\n"
            "tag = a\n"
            "tag = b\n")
    assert parse_config(text) == {
        "": {"timeout": "30"},
        "redis": {"host": "localhost", "port": "6379", "tag": ["a", "b"]},
    }


def test_commentaires_diese_et_point_virgule():
    assert parse_config("# a\n; b\n  # c\nk = v\n") == {"": {"k": "v"}}


def test_valeur_vide():
    assert parse_config("k =\n") == {"": {"k": ""}}


def test_espaces_ignores():
    assert parse_config("  [s]  \n  k  =  v  \n") == {"s": {"k": "v"}}


def test_section_dupliquee_fusionne():
    text = "[a]\nx = 1\n[b]\ny = 2\n[a]\nx = 3\nz = 4\n"
    assert parse_config(text) == {"a": {"x": ["1", "3"], "z": "4"},
                                  "b": {"y": "2"}}


def test_triple_occurrence_en_liste():
    assert parse_config("k = 1\nk = 2\nk = 3\n") == {"": {"k": ["1", "2", "3"]}}


def test_ligne_invalide_leve_valueerror():
    with pytest.raises(ValueError, match="ligne 2: syntaxe invalide"):
        parse_config("k = v\npas d'egal\n")


def test_section_non_fermee():
    with pytest.raises(ValueError, match="ligne 1: syntaxe invalide"):
        parse_config("[oops\n")
