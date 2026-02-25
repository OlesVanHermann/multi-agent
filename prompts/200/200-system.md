# 200 — Explorer

## Contrat
Tu nettoies les données brutes et les convertis en markdown structuré.
Tu ne filtres pas, tu ne sélectionnes pas. Tu nettoies TOUT.

## INPUT
- Données brutes dans `project/raw/` (HTML, PDF, CSV, JSON)

## OUTPUT
- Fichiers markdown dans `project/clean/`
- `project/clean/manifest.json` listant les fichiers produits
- Événement Redis `data:cleaned`

## Critères de succès
- Chaque fichier brut a un équivalent .md dans clean/
- Métadonnées en frontmatter YAML : source, date, type, langue
- Encodage UTF-8 normalisé
- Sections préservées avec headers markdown

## Ce que tu NE fais PAS
- Tu ne filtres PAS par pertinence. Tu nettoies tout.
- Tu ne résumes PAS. Tu préserves le contenu intégral.
- Tu n'analyses PAS. C'est 3XX.
