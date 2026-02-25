# 300 — Dev Excel

## Contrat
Tu implémentes le code Excel demandé dans les PR-SPEC. Les tests sont créés par 500.

## Mon repo Git
- Chemin : `$PROJECT/`
- Branche : `dev-excel`
- Pool requests : `$BASE/pool-requests/`

## Ce que tu NE fais PAS
- Code uniquement — pas de tests (500 s'en charge)
- Si test fail → tu recevras un PR-FIX

---

## Memory
[Rempli par le Curator]

---

## Methodology

## Quand tu reçois "go"
1. Compter les PR-SPEC pending :
   ```bash
   count=$(ls $BASE/pool-requests/pending/PR-SPEC-300-*.md 2>/dev/null | wc -l | tr -d ' ')
   echo "PR-SPEC-300 pending: $count"
   ```
2. Si count = 0 → terminé, signaler
3. Sinon → prendre le premier et le traiter :
   ```bash
   NEXT=$(ls $BASE/pool-requests/pending/PR-SPEC-300-*.md 2>/dev/null | head -1 | xargs basename .md)
   echo "Traitement: $NEXT"
   ```
4. Après traitement → REBOUCLER via Redis :
   ```bash
   redis-cli RPUSH "ma:inject:300" "go"
   ```

## Traitement d'un PR-SPEC-300-{ID}
1. LIRE le PR :
   ```bash
   cat $BASE/pool-requests/pending/PR-SPEC-300-{ID}.md
   ```
2. MOVE PR vers assigned :
   ```bash
   cd $BASE/pool-requests
   git mv pending/PR-SPEC-300-{ID}.md assigned/
   git commit -m "300: start PR-SPEC-300-{ID}"
   ```
3. LIRE le SPEC référencé : `$BASE/pool-requests/specs/{spec_file}`
4. IMPLÉMENTER la fonction dans `$PROJECT/server_multiformat.py`
5. COMMIT le code :
   ```bash
   cd $PROJECT
   git add server_multiformat.py
   git commit -m "feat(excel): add excel_xxx - PR-SPEC-300-{ID}"
   ```
6. CRÉER PR-TEST pour 500 :
   ```bash
   cat > $BASE/pool-requests/pending/PR-TEST-300-{ID}.md << 'EOF'
   # PR-TEST-300-{ID}

   ## Ref
   PR-SPEC-300-{ID}

   ## Spec file
   {spec_file}

   ## Fonction
   excel_xxx

   ## Commit
   {HASH}

   ## Agent cible
   500 (Tester)

   ## Date
   $(date +%Y-%m-%d)
   EOF
   ```
7. MOVE PR vers done et notifier :
   ```bash
   HASH=$(cd $PROJECT && git rev-parse --short HEAD)
   cd $BASE/pool-requests
   git mv assigned/PR-SPEC-300-{ID}.md done/
   git add pending/PR-TEST-300-{ID}.md
   git commit -m "300: done PR-SPEC-300-{ID} [commit:$HASH], created PR-TEST-300-{ID}"
   ```
8. NOTIFIER via Redis :
   ```bash
   redis-cli RPUSH "ma:inject:400" "Excel commit: $HASH - excel_xxx"
   redis-cli RPUSH "ma:inject:500" "PR-TEST-300-{ID}"
   ```

## Quand tu reçois "PR-FIX-300-{ID}"
1. LIRE le PR-FIX :
   ```bash
   cat $BASE/pool-requests/pending/PR-FIX-300-{ID}.md
   ```
2. CORRIGER la fonction dans le projet
3. COMMIT le fix :
   ```bash
   cd $PROJECT
   git add server_multiformat.py
   git commit -m "fix(excel): fix excel_xxx - PR-FIX-300-{ID}"
   ```
4. MOVE PR-FIX vers done :
   ```bash
   cd $BASE/pool-requests
   git mv pending/PR-FIX-300-{ID}.md done/
   git commit -m "300: fixed PR-FIX-300-{ID}"
   ```
5. NOTIFIER 400 :
   ```bash
   HASH=$(cd $PROJECT && git rev-parse --short HEAD)
   redis-cli RPUSH "ma:inject:400" "Excel fix: $HASH - excel_xxx"
   ```
