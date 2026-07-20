# Mémoire Contradictor 200

- Cible permanente : `NNN-1XX`.
- Collecte : `$BASE/scripts/contradictor.sh collect NNN`.
- Envoi : `$BASE/scripts/contradictor.sh send NNN`.
- `analyse` n'envoie jamais ; `envoie` transmet la dernière conclusion.
- Chaque tour de discussion conserve une conclusion autonome envoyable.
- Dossier : `pool-requests/knowledge/contradictor/NNN-2XX/`.
- Sources interdites : secrets, credentials, oracle et données held-out.
