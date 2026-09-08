# Méthodologie Contradictor 200


## Optimisation du pilotage périodique — `revise-prompt-1XX`

Ta tâche planifiée de 6 h, suspendue tant que l'opérateur ne l'active pas,
analyse le fonctionnement réel du triangle puis améliore uniquement le texte
du prompt planifié de ton Master. Compare l'objectif utilisateur d'origine, le
prompt crontab actuel et l'état durable (`USER_RESULT_CONTRACT`, cycles,
corrélations et terminaux datés). Une preuve absente reste `INDÉTERMINÉ`.

Utilise `contradictor.sh collect NNN`, sans exploration manuelle de tmux/Redis,
puis `contradictor.sh revise-prompt NNN` avec le nouveau texte sur stdin. Ne
change aucun nom, période ou statut, aucun autre fichier crontab ou prompt
d'agent, et n'écris pas dans l'état du triangle. Cette capacité reste
consultative : aucun `DONE`, transition ou dispatch. Si aucun gain concret
n'est possible : `NOOP`, silence total.


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

## Cascade des tâches planifiées — v3.2.22

## `revise-prompt-1XX`

1. Exécuter une fois `$BASE/scripts/contradictor.sh collect NNN` et lire l'état
   durable sous `pool-requests/state/` (`USER_RESULT_CONTRACT`, cycles et
   terminaux datés). Ne pas explorer tmux/Redis manuellement.
2. Comparer l'objectif utilisateur d'origine, le prompt crontab actuel du
   Master et l'état physique/durable constaté. Une preuve absente reste
   `INDÉTERMINÉ`, jamais une affirmation inventée.
3. Repérer les répétitions, consignes périmées et blocages résolus ou encore
   réels ; référencer le cycle et la corrélation exacts à reprendre.
4. Préparer un prompt Master ciblant la phase courante, conservant les objectifs,
   l'interdiction de réémettre un `DELIVERED`, `NOOP` si tout est en vol et le
   critère d'arrêt décidé par l'utilisateur.
5. Si aucun prompt Master n'existe, construire un premier texte idempotent
   dérivé de l'objectif et de l'état durable : constat sur preuves, prochain
   lot, une relance maximum, blocage immédiat et jalon final opérateur. Exécuter
   `printf '%s\n' "$NOUVEAU_PROMPT" | $BASE/scripts/contradictor.sh revise-prompt NNN`.
   Il crée exclusivement `NNN-1XX_120.prompt.suspended`.
6. Sinon, exécuter `printf '%s\n' "$NOUVEAU_PROMPT" | $BASE/scripts/contradictor.sh revise-prompt NNN`.
   Le script sauvegarde l'ancien texte et préserve nom, période et statut.
7. Si créé ou modifié, envoyer au seul `NNN-1XX` une conclusion de une à trois lignes.
   Si déjà optimal : `NOOP`, silence total.

Ne modifier aucun autre fichier de `crontab/`, aucun prompt d'agent et jamais
le tien. Une divergence avec une décision utilisateur est signalée, pas tranchée.
Cette capacité ne donne aucune autorité de `DONE`, transition ou dispatch et
n'autorise aucune écriture dans `pool-requests/state/`.
Réussite observable : le prochain tir produit un nouveau lot ou un blocage
remonté, zéro répétition livrée/en vol, et réduit l'écart à l'objectif.

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
