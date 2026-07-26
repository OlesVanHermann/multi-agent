# Méthodologie Contradictor 012-212


### Demande utilisateur non attribuée

Si `analysis_view.user_requests` est vide, les historiques et panes du `1XX`
ne sont que des candidats non attribués. Signale cette incertitude et conclus
`INDÉTERMINÉ` si leur origine ne peut être établie. Ne substitue jamais un
fichier `system.md`, `memory.md` ou `methodology.md` à la demande utilisateur.


## Méthode d'audit utilisateur — v3.2.7

Cet ordre remplace toute séquence antérieure contradictoire :

1. `USER_REQUEST` : demande initiale au `1XX`, amendements, résultat attendu.
2. `AGENT_INSTRUCTION` : rôles et contraintes, sans les confondre avec la demande.
3. `INTER_AGENT_MESSAGE` : décisions, dispatchs, réponses et terminaux de tout le triangle.
4. `PHYSICAL_EVIDENCE` : code, artefacts, commits, hashes et tests.
5. Verdict séparé sur exécution, développement, validation et livraison.
6. Écart causal puis plan concret jusqu'au résultat final attendu.

La conclusion contient toutes les rubriques canoniques de
`docs/CONTRADICTOR.md`. Une preuve absente vaut `INDÉTERMINÉ`.

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
