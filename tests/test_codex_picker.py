"""Picker /model de Codex : le modèle doit être trouvé quelle que soit la casse.

Incident ma2 2026-10-07 : codex-cli 0.160.1 affiche « 5. GPT-5.6-Sol » ;
la recherche sensible à la casse de « gpt-5.6-sol » échouait, le picker était
refermé et l'agent restait sur le modèle par défaut (GPT-6.1-Sol).
"""

import os
import re
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
ENGINES_SH = os.path.join(BASE_DIR, "scripts", "engines.sh")

# Relevé sur codex-cli 0.160.1 (session jetable codex1a, ma2).
PICKER_0_160_1 = """\
  Select Model and Effort
› 1. GPT-6.1-Sol (current)  Latest workhorse model for coding and everyday work.
  2. GPT-6-Astra            Frontier intelligence for the most demanding work.
  3. GPT-6-Sol              Previous generation workhorse model.
  4. GPT-6-Luna             Fast and affordable model for easier tasks.
  5. GPT-5.6-Sol            Older generation workhorse model.
  6. GPT-5.6-Terra          Older balanced model for straightforward work.
  7. GPT-5.6-Luna           Older fast and efficient model.
"""


def _digit_command():
    """Ligne de engines.sh qui extrait le chiffre du modèle dans le picker."""
    with open(ENGINES_SH) as f:
        for line in f:
            if re.search(r'digit=\$\(printf .* \$\{model\}', line):
                return line.strip()
    raise AssertionError("extraction du chiffre de modèle introuvable dans engines.sh")


def test_model_digit_is_case_insensitive():
    command = _digit_command()
    script = f'pane="$1"; model="$2"; {command}; printf "%s" "$digit"'
    expected = {"gpt-5.6-sol": "5", "gpt-6-astra": "2", "gpt-6-sol": "3",
                "gpt-5.6-luna": "7", "gpt-6.1-sol": "1"}
    for model, digit in expected.items():
        r = subprocess.run(["bash", "-c", script, "_", PICKER_0_160_1, model],
                           capture_output=True, text=True, timeout=10)
        assert r.stdout == digit, f"{model}: {r.stdout!r} {r.stderr}"
