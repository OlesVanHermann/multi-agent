#!/bin/bash
# check-secrets.sh — Garde-fou anti-fuite de secrets (D3)
#
# Vérifie, avant release (hub-release.sh) et en CI (security.yml) :
#   1. qu'aucun secrets.cfg n'est tracké par git ;
#   2. que setup/secrets.cfg local (s'il existe) ne contient plus de
#      valeurs par défaut (changeme/admin/vide) ;
#   3. scan gitleaks si l'outil est installé (sinon délégué à la CI).
#
# Code retour : 0 = OK, 1 = problème détecté (release/CI doit échouer).

set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BASE"

FAIL=0

# ── 1. secrets.cfg ne doit jamais être tracké ────────────────────────────
TRACKED=$(git ls-files -- '*secrets.cfg' || true)
if [ -n "$TRACKED" ]; then
    echo "[FAIL] secrets.cfg tracké par git (ne doit JAMAIS être commité) :"
    echo "$TRACKED" | sed 's/^/    /'
    FAIL=1
fi

# ── 2. Valeurs par défaut dans le secrets.cfg local ──────────────────────
# Mêmes valeurs refusées qu'au démarrage infra (C1) : vide/admin/changeme.
if [ -f setup/secrets.cfg ]; then
    DEFAULTS=$(grep -nE '^(KEYCLOAK_ADMIN_PASSWORD|HEALTH_TOKEN)=(changeme|admin|password|)[[:space:]]*$' setup/secrets.cfg || true)
    if [ -n "$DEFAULTS" ]; then
        echo "[FAIL] Valeurs par défaut dans setup/secrets.cfg :"
        echo "$DEFAULTS" | sed 's/^/    /'
        echo "       Définir des valeurs fortes avant de continuer."
        FAIL=1
    fi
fi

# ── 3. Scan gitleaks (optionnel en local, exécuté systématiquement en CI) ─
if command -v gitleaks &>/dev/null; then
    if ! gitleaks detect --source . --no-banner --redact; then
        echo "[FAIL] gitleaks a détecté un secret potentiel."
        FAIL=1
    fi
else
    echo "[WARN] gitleaks non installé — scan anti-secrets délégué à la CI (security.yml)."
fi

if [ "$FAIL" -eq 0 ]; then
    echo "[OK] Aucun secret tracké, pas de valeur par défaut."
fi
exit "$FAIL"
