# 100-700 — Methodology

## Étapes
1. Lire `prompts/100/100-system.md` pour comprendre les besoins de 100
2. Lire `project-config.md` pour la configuration pipeline
3. Scanner Redis pour l'état de chaque agent
4. Lire les bilans récents pour identifier les blocages
5. Synthétiser :
   - Chaîne pipeline avec ordre
   - État de chaque agent (idle, busy, done, error)
   - Blocages et raisons
6. Vérifier < 3000 tokens
7. Écrire dans `prompts/100/100-memory.md`
