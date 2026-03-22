#!/bin/bash
# genpass.sh - Générateur de mot de passe 16 chars avec entropie temporelle

set -u

# Étape 1 : générer 16 durées de sleep (100 à 900 ms)
SLEEPS=()
for i in $(seq 1 16); do
  VAL=$(od -An -tu1 -N1 /dev/urandom | tr -d ' ')
  SLEEP_MS=$(( (VAL % 9 + 1) * 100 ))
  SLEEPS+=("$SLEEP_MS")
done

TOTAL=0
for s in "${SLEEPS[@]}"; do
  TOTAL=$((TOTAL + s))
done

echo "Durées de sleep (ms) : ${SLEEPS[*]}"
echo "Temps total estimé : ${TOTAL}ms (~$((TOTAL / 1000))s)"
echo ""
echo "Génération en cours..."

# Étape 2 : pour chaque caractère, sleep puis extraire 1 char
PASSWORD=""
for i in $(seq 0 15); do
  DELAY_MS=${SLEEPS[$i]}
  DELAY_S=$(awk "BEGIN {printf \"%.1f\", ${DELAY_MS}/1000}")
  printf "  [%2d/16] sleep %dms..." "$((i + 1))" "$DELAY_MS"
  sleep "$DELAY_S"
  CHAR=$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 1)
  PASSWORD="${PASSWORD}${CHAR}"
  printf " → '%s'\n" "$CHAR"
done

echo ""
echo "$PASSWORD"
