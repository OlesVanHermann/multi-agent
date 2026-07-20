# Méthodologie Contradictor 2XX

## `analyse`

1. Exécuter une fois `$BASE/scripts/contradictor.sh collect __TRIANGLE__`.
2. Lire d'abord `analysis_view`; consulter les preuves brutes du snapshot
   uniquement pour citer ou vérifier un constat.
3. Produire au maximum cinq constats prouvés.
4. Écrire `report.md` et `conclusion.md` dans le dossier Contradictor.
5. Maintenir une conclusion autonome pendant toute discussion.

Ne jamais compenser une preuve absente par une exploration manuelle non bornée.

## `envoie`

Exécuter `$BASE/scripts/contradictor.sh send __TRIANGLE__` et confirmer la preuve
d'envoi. Aucun `DONE` et aucune transition de workflow.
