# 200 — Methodology

## Conversion par type

### HTML → markdown
1. Extraire le contenu principal (article, main, body)
2. Supprimer : nav, header, footer, aside, script, style
3. Convertir les balises en markdown
4. Ajouter frontmatter YAML

### CSV/JSON → markdown
1. Créer un tableau markdown
2. Si > 100 lignes, découper par groupe logique
3. Ajouter frontmatter avec schéma des colonnes

### PDF → markdown
1. Extraction texte
2. Reconstituer les paragraphes
3. Ajouter frontmatter YAML

## Frontmatter standard
source, date_collecte, type, langue, taille_originale

## Nommage
{source}_{titre_slugifié}_{date}.md
