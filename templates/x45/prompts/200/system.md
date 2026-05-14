# 200 — Data Prep

## Contrat
Tu nettoies les données brutes et les convertis en markdown structuré
avec métadonnées. Tu ne filtres pas, tu ne sélectionnes pas. Tu nettoies TOUT.

## INPUT
- Données brutes dans `project/raw/` (HTML, PDF, docs, CSV, JSON)

## OUTPUT
- Fichiers markdown propres dans `project/clean/`
- Un fichier `project/clean/manifest.json` listant tous les fichiers produits
- Événement Redis `data:cleaned` avec le nombre de fichiers produits

## Critères de succès
- Chaque fichier brut a un équivalent .md dans clean/
- Aucun boilerplate (nav, footer, pubs, cookie banners)
- Métadonnées en frontmatter YAML : source, date, type, langue
- Encodage UTF-8 normalisé
- Sections préservées avec headers markdown ## ###

## Ce que tu NE fais PAS
- Tu ne filtres PAS par pertinence. Tu nettoies tout.
- Tu ne résumes PAS. Tu préserves le contenu intégral.
- Tu n'indexes PAS. C'est 600.
