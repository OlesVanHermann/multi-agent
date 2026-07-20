# Méthodologie Contradictor 200

## `analyse`

1. Exécuter une seule fois `$BASE/scripts/contradictor.sh collect NNN`.
2. Lire d'abord `analysis_view`; consulter les preuves brutes du même snapshot
   uniquement pour citer ou vérifier un constat.
3. Construire demande → compréhension → décision → action → résultat.
4. Produire au maximum cinq constats, avec preuve et correction minimale.
5. Écrire `report.md` et `conclusion.md` sous le dossier Contradictor.
6. Terminer chaque réponse par `## Conclusion proposée pour NNN-1XX`.

Une preuve indisponible devient `NON CONCLUANT`, jamais une nouvelle exploration
manuelle de tmux, Redis, logs, plans ou projet.

## `envoie`

Exécuter `$BASE/scripts/contradictor.sh send NNN`. Ne recopier ni reconstruire
le message : le script transmet exactement `conclusion.md`.
