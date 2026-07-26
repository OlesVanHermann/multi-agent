# Méthodologie Contradictor 200


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

## `analyse`

1. Exécuter une seule fois `$BASE/scripts/contradictor.sh collect NNN`.
2. Lire d'abord `analysis_view.user_requests` : demande initiale, amendements,
   dernière intention applicable.
   Si la liste est vide, utiliser seulement les candidats non attribués de
   l'historique/pane du `1XX`, en signalant l'incertitude ; ne jamais substituer
   un fichier de prompt d'agent.
3. Lire `evidence.agent_prompt_files` séparément, uniquement pour comprendre
   les rôles ; ne jamais les appeler « prompt utilisateur ».
4. Reconstituer les échanges de chaque agent `NNN-YXX`.
5. Confronter les annonces aux preuves physiques, puis qualifier exécution,
   développement, validation et livraison.
6. Produire le plan exécutable par `NNN-1XX` pour toute dimension non prouvée.
7. Écrire `report.md` et `conclusion.md` sous le dossier Contradictor avec
   toutes les rubriques canoniques de `docs/CONTRADICTOR.md`.

Une preuve indisponible devient `NON CONCLUANT`, jamais une nouvelle exploration
manuelle de tmux, Redis, logs, plans ou projet.

## `envoie`

Exécuter `$BASE/scripts/contradictor.sh send NNN`. Ne recopier ni reconstruire
le message : le script transmet exactement `conclusion.md`, uniquement au
`NNN-1XX`.
