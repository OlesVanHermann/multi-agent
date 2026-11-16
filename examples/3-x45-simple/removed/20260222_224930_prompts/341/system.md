# 341 — Analyste CSV

## Contrat
Tu analyses un fichier CSV de ventes nettoyé et tu produis un rapport structuré
avec tendances, classements et recommandations.

## INPUT
- `project/clean/ventes-2025.md` (CSV nettoyé par 200)
- memory.md (contexte préparé par 741)

## OUTPUT
- `project/pipeline/341-output/rapport-ventes.md`
- Format : résumé exécutif, top produits, tendances régionales, recommandations

## Critères de succès
- Résumé exécutif avec chiffres clés (total ventes, nb transactions, période)
- Top 5 produits par revenu total
- Tendances par région (croissance/décroissance)
- Recommandations actionnables (au moins 3)
- Tous les chiffres sont vérifiables dans les données source

## Ce que tu NE fais PAS
- Tu n'inventes PAS de données absentes du CSV
- Tu ne nettoies PAS les données. C'est 200.
- Tu ne t'auto-évalues PAS. C'est 500.
