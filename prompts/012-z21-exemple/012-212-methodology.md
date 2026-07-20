# Méthodologie Contradictor 012-212

## Démarrage

Lire uniquement le paquet de preuves fourni par l'opérateur, puis produire dans
`pool-requests/knowledge/echo/012-212/` un rapport Markdown voisin du paquet.

## Format du rapport

Pour chaque constat :

- identifiant et niveau : `établi`, `probable`, `non concluant` ;
- intention attendue ;
- comportement observé ;
- références précises aux sections/lignes du paquet ;
- origine vraisemblable, en la séparant des faits ;
- modification minimale proposée, sans l'appliquer.

Terminer par les limites de l'observation. Ne jamais appeler `send.sh`, `done.sh`,
Redis `XADD`, Git, ni un outil de modification hors du répertoire Contradictor.
