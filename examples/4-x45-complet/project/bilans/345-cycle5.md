# Bilan 345 — Cycle 5
Score : 97% (stabilisé)
## Problèmes
- P1 (moyen) : pas de reconnexion automatique si connexion UNO perdue mid-session.
  _get_or_connect() cache le desktop mais ne vérifie pas s'il est encore valide.
  Si LO redémarre, le cache est périmé → erreur jusqu'au restart du serveur MCP
- P2 (mineur) : pas de graceful shutdown — SIGTERM non intercepté,
  pas de cleanup de la connexion UNO
- P3 (mineur) : to_thread sur doc.getSheets().getByName() — le getSheets() est
  aussi un appel UNO, il devrait être wrappé séparément

## Progression
60% → 82% → 95% → 97% → 97% (stabilisation haute)
