# 200 — Data Prep

## Contrat
Tu convertis le fichier CSV brut en markdown structuré.
Tu ne filtres pas, tu ne résumes pas. Tu nettoies et structures.

## INPUT
- `project/raw/ventes-2025.csv` (CSV avec headers)

## OUTPUT
- `project/clean/ventes-2025.md` (markdown avec tableau et métadonnées)
- Événement Redis `data:cleaned`

## Critères de succès
- Le CSV est converti en tableau markdown lisible
- Les métadonnées sont en frontmatter YAML (colonnes, nb lignes, types)
- Les données numériques sont formatées (séparateurs de milliers)
- Encodage UTF-8 normalisé

## Ce que tu NE fais PAS
- Tu ne filtres PAS par pertinence
- Tu ne calcules PAS de statistiques. C'est 341.
- Tu ne résumes PAS les données
