# Méthodologie Contradictor 280


## Cascade des tâches planifiées — v3.2.22

Le créateur écrit ta tâche 6 h sous `NNN-2XX_360.prompt.suspended`. Au tir
activé par l'opérateur, collecte l'état réel. Si ton Master n'a aucun prompt
planifié, construis depuis l'objectif utilisateur et l'état durable un premier
pilotage idempotent, puis crée uniquement `NNN-1XX_120.prompt.suspended` via
`contradictor.sh revise-prompt NNN`. Ne l'active jamais.

Si le prompt Master existe, améliore uniquement son texte via
`contradictor.sh revise-prompt NNN`. Ne change aucun nom, période ou statut,
aucun autre fichier crontab ou prompt d'agent. Aucun `DONE`, transition ou
dispatch. Si aucun gain concret n'est possible : `NOOP`, silence total.


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

## `analyse`

1. Exécuter une fois `$BASE/scripts/contradictor.sh collect 180`.
2. Lire d'abord `analysis_view`; consulter les preuves brutes du snapshot
   uniquement pour citer ou vérifier un constat.
3. Produire au maximum cinq constats prouvés.
4. Écrire `report.md` et `conclusion.md` dans le dossier Contradictor.
5. Maintenir une conclusion autonome pendant toute discussion.

Ne jamais compenser une preuve absente par une exploration manuelle non bornée.

## `envoie`

Exécuter `$BASE/scripts/contradictor.sh send 180` et confirmer la preuve
d'envoi. Aucun `DONE` et aucune transition de workflow.
