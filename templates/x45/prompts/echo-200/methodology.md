# Méthodologie Contradictor 200

## `analyse`

1. Exécuter une seule fois `$BASE/scripts/contradictor.sh collect NNN`.
2. Lire `analysis_scope` puis `analysis_view.activity_by_agent` afin de couvrir
   chaque agent `NNN-YXX`; consulter les preuves brutes du même snapshot
   uniquement pour citer ou vérifier un constat.
3. Reconstruire la séquence demande → dispatchs → actions des satellites →
   résultats → état actuel du triangle.
4. Produire au maximum cinq constats, puis une relance ordonnée et directement
   exécutable par le `NNN-1XX`.
5. Écrire `report.md` et `conclusion.md` sous le dossier Contradictor.
6. Terminer chaque réponse par `## Conclusion proposée pour NNN-1XX`, contenant
   `Synthèse du triangle` et `Relance du développement`.

Une preuve indisponible devient `NON CONCLUANT`, jamais une nouvelle exploration
manuelle de tmux, Redis, logs, plans ou projet.

## `envoie`

Exécuter `$BASE/scripts/contradictor.sh send NNN`. Ne recopier ni reconstruire
le message : le script transmet exactement `conclusion.md`, uniquement au
`NNN-1XX`.
