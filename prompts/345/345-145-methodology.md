# 345-145 — Methodology

## Préfixe Redis
Utiliser le préfixe `mi:` pour toutes les commandes Redis.

## Phase 0 — Bootstrap

1. Publier ton démarrage :
   ```
   redis-cli XADD "mi:agent:345-145:outbox" '*' from "345-145" type "status" payload "started"
   ```
2. Dispatcher 345-945 (Triangle Architect) pour écrire/vérifier les system.md et memory.md :
   ```
   redis-cli XADD "mi:agent:345-945:inbox" '*' prompt "bootstrap: écrire/vérifier system.md et memory.md du triangle" from_agent "345-145" timestamp "$(date +%s)"
   ```
3. Attendre `345-945:done` sur ton inbox (polling 60s)
4. Passer à Phase 1 Cycle 1

## Phase 1 — Boucles qualité (Cycles 1 à 6)

Pour chaque cycle N (de 1 à 6) :

### Étape A — Curator (345-745)
5. Dispatcher 345-745 :
   ```
   redis-cli XADD "mi:agent:345-745:inbox" '*' prompt "cycle {N}: préparer memory.md de 345" from_agent "345-145" timestamp "$(date +%s)"
   ```
6. Attendre `345-745:done` sur ton inbox

### Étape B — Main (345)
7. Dispatcher 345 :
   ```
   redis-cli XADD "mi:agent:345:inbox" '*' prompt "cycle {N}: exécuter ton contrat" from_agent "345-145" timestamp "$(date +%s)"
   ```
8. Attendre `345:done` sur ton inbox

### Étape C — Observer (345-545)
9. Dispatcher 345-545 :
   ```
   redis-cli XADD "mi:agent:345-545:inbox" '*' prompt "cycle {N}: évaluer l'output de 345" from_agent "345-145" timestamp "$(date +%s)"
   ```
10. Attendre `345-545:done:score:{SCORE}` sur ton inbox
11. Extraire le SCORE du message

### Étape D — Décision
12. Si SCORE ≥ 98% ET score précédent ≥ 98% (2 cycles stables) → Phase 2 (DONE)
13. Si SCORE stagne 2 cycles après Coach → boucle longue :
    - Dispatcher 345-945 (Triangle Architect) pour réécrire les contrats
    - Attendre `345-945:done`
    - Reprendre au cycle N+1
14. Sinon → boucle courte :
    - Dispatcher 345-845 (Coach) :
      ```
      redis-cli XADD "mi:agent:345-845:inbox" '*' prompt "cycle {N}: améliorer methodology de 345 — score={SCORE}" from_agent "345-145" timestamp "$(date +%s)"
      ```
    - Attendre `345-845:done`
    - Reprendre au cycle N+1
15. Si cycle 6 atteint sans convergence → Phase 2 (DONE forcé)

## Phase 2 — Complétion

16. Publier le résultat final :
    ```
    redis-cli XADD "mi:agent:345-145:outbox" '*' from "345-145" type "done" payload "triangle-345-complete:score:{SCORE_FINAL}:cycles:{N}"
    ```
17. Signaler complétion à 100 (Master global) :
    ```
    redis-cli XADD "mi:agent:100:inbox" '*' prompt "345-145:done:score:{SCORE_FINAL}" from_agent "345-145" timestamp "$(date +%s)"
    ```

## Règles
- Chaque dispatch produit un log sur outbox
- Timeout 10 min par agent → signaler à 100
- Ne jamais dispatcher 2 agents en parallèle dans le triangle
- Ordre strict : 745 → 345 → 545 → décision → (845 ou 945) → cycle suivant
