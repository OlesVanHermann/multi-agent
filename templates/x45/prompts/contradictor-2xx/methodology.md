# Méthodologie Contradictor 2XX


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
