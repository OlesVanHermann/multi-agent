#!/bin/bash
# Oracle s01-slugify — tests d'acceptation cachés (permissions.deny bench/oracle/**).
# Exécuté par verifier.py avec cwd = répertoire projet de l'agent.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
exec python3 -m pytest "$HERE/test_oracle.py" -q --no-header -p no:cacheprovider
