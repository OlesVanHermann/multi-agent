# Méthodologie Contradictor 2XX

## `analyse`

1. Exécuter une fois `$BASE/scripts/contradictor.sh collect __TRIANGLE__`.
2. Lire `analysis_scope` puis `analysis_view.activity_by_agent` pour couvrir
   tous les agents du triangle; consulter les preuves brutes du snapshot
   uniquement pour citer ou vérifier un constat.
3. Produire au maximum cinq constats prouvés, une synthèse de ce qui s'est
   passé et une séquence d'actions pour relancer le développement.
4. Écrire `report.md` et `conclusion.md` dans le dossier Contradictor.
5. Maintenir une conclusion autonome pendant toute discussion.

Ne jamais compenser une preuve absente par une exploration manuelle non bornée.

## `envoie`

Exécuter `$BASE/scripts/contradictor.sh send __TRIANGLE__` et confirmer la preuve
d'envoi au seul `__MAIN__`. Aucun `DONE` et aucune transition de workflow.
