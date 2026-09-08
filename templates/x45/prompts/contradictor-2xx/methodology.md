# Méthodologie Contradictor 2XX


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

1. Exécuter une fois `$BASE/scripts/contradictor.sh collect __TRIANGLE__` et
   lire l'état durable sous `pool-requests/state/` (`USER_RESULT_CONTRACT`,
   cycles et terminaux datés). Ne pas explorer tmux/Redis manuellement.
2. Comparer l'objectif utilisateur d'origine, le prompt crontab actuel du
   Master et l'état physique/durable constaté. Une preuve absente reste
   `INDÉTERMINÉ`, jamais une affirmation inventée.
3. Repérer les répétitions, consignes périmées et blocages résolus ou encore
   réels ; référencer le cycle et la corrélation exacts à reprendre.
4. Préparer un prompt Master ciblant la phase courante, conservant les objectifs,
   l'interdiction de réémettre un `DELIVERED`, `NOOP` si tout est en vol et le
   critère d'arrêt décidé par l'utilisateur.
5. Exécuter `printf '%s\n' "$NOUVEAU_PROMPT" | $BASE/scripts/contradictor.sh revise-prompt __TRIANGLE__`.
   Le script limite l'écriture au seul prompt crontab de `__MAIN__`, sauvegarde
   l'ancien texte et préserve nom, période et statut actif/suspendu. Si
   `__MAIN__` ne possède encore aucun prompt planifié, le script le crée à son
   nom canonique `__MAIN___120.prompt.suspended` (2 h) — toujours suspendu,
   activation exclusivement opérateur.
6. Si modifié, envoyer au seul `__MAIN__` une conclusion de une à trois lignes
   indiquant quoi et pourquoi. Si déjà optimal : `NOOP`, silence total.

Ne modifier aucun autre fichier de `crontab/`, aucun prompt d'agent et jamais
le tien. Une divergence avec une décision utilisateur est signalée, pas tranchée.
Cette capacité ne donne aucune autorité de `DONE`, transition ou dispatch et
n'autorise aucune écriture dans `pool-requests/state/`.
Réussite observable : le prochain tir produit un nouveau lot ou un blocage
remonté, zéro répétition livrée/en vol, et réduit l'écart à l'objectif.

## `analyse`

1. Exécuter une fois `$BASE/scripts/contradictor.sh collect __TRIANGLE__`.
2. Lire d'abord `analysis_view.user_requests` dans l'ordre. Identifier la
   demande initiale, ses amendements et le dernier résultat attendu.
   Si cette liste est vide, examiner
   `unattributed_request_candidates` et les panes du `1XX`, les signaler comme
   candidats non attribués et conclure `INDÉTERMINÉ` si leur origine ne peut
   pas être établie. Ne jamais utiliser un prompt d'agent comme remplacement.
3. Lire séparément `evidence.agent_prompt_files` uniquement pour comprendre le
   rôle des agents. Ne jamais en extraire la demande utilisateur.
4. Reconstituer `inter_agent_exchanges` et `activity_by_agent` pour tous les
   agents du triangle.
5. Confronter les déclarations à `physical_evidence`, aux artefacts et aux
   tests, puis qualifier séparément :
   `Exécution du prompt`, `Développement réalisé`, `Validation réalisée` et
   `Résultat effectivement livré`.
6. Si une dimension vaut `NON`, `PARTIEL` ou `INDÉTERMINÉ`, produire un plan
   directement exécutable par le Master. Si tout est réalisé, proposer
   seulement la vérification ou livraison encore nécessaire.
7. Écrire `report.md` et `conclusion.md` dans le dossier Contradictor.
8. Maintenir une conclusion autonome pendant toute discussion.

`conclusion.md` contient exactement les rubriques canoniques documentées dans
`docs/CONTRADICTOR.md`, dont le plan, les agents, l'ordre de relance et les
critères d'acceptation.

Ne jamais compenser une preuve absente par une exploration manuelle non bornée.

## `envoie`

Exécuter `$BASE/scripts/contradictor.sh send __TRIANGLE__` et confirmer la preuve
d'envoi au seul `__MAIN__`. Aucun `DONE` et aucune transition de workflow.
