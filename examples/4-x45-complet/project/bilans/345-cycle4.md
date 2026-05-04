# Bilan 345 — Cycle 4
Score : 95% (stagnation)
## Problèmes
- P1 (important) : appels UNO synchrones dans fonctions async — bloque l'event loop.
  connect_uno(), getByName(), getCellRangeByName() sont BLOQUANTS.
  Doit utiliser asyncio.to_thread()
- P2 (moyen) : aucun logging — erreurs visibles uniquement côté client MCP
- P3 (moyen) : nouvelle connexion UNO créée à chaque appel. Pas de réutilisation.
## Progression
60% → 82% → 95% → 95% (stagnation)
