# 000-800 — Methodology

## Étapes
1. Lire le dernier bilan de 000-500 dans `bilans/000-cycle*.md`
2. Lire la methodology actuelle de 000
3. Pour chaque problème identifié dans le bilan :
   - Formuler une règle corrective concrète
   - Exemple : si "chaîne incomplète" → ajouter "vérifier que output N = input N+1"
4. Intégrer les nouvelles règles dans la methodology existante
5. Conserver les règles qui fonctionnent (score > 80%)
6. Écrire la methodology mise à jour dans `prompts/000/000-methodology.md`

## Principes
- Une règle = un problème. Pas de règles vagues.
- Préférer les exemples concrets aux instructions abstraites
- Si un problème revient 2 cycles de suite, escalader à 000-900 via Redis
