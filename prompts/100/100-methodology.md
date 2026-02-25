# 100 — Methodology

## Étapes
1. Lire la configuration pipeline dans memory.md
2. Vérifier l'état de chaque agent via Redis
3. Identifier le prochain agent à dispatcher :
   - Ses inputs sont-ils prêts ?
   - Son prédécesseur a-t-il terminé ?
4. Dispatcher via Redis : `agent:{ID}:inbox`
5. Attendre la complétion (status = "done")
6. Passer au suivant
7. Quand tous ont terminé, signaler à 000

## Règles
- Ne jamais dispatcher un agent dont les inputs ne sont pas prêts
- Si un agent est bloqué > 10 minutes, signaler à 000
- Loguer chaque dispatch avec timestamp
- Respecter l'ordre : 200 → 341 → 342 → 345 (ou selon config)
