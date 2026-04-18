# 200 — Methodology

## Conversion par type

### HTML → markdown
1. Extraire le contenu principal (article, main, body)
2. Supprimer : nav, header, footer, aside, script, style, cookie banners
3. Convertir les balises en markdown (h1→#, p→paragraphe, ul→liste)
4. Préserver les tableaux, liens, images (chemins relatifs → absolus)
5. Ajouter frontmatter YAML

### PDF → markdown
1. Extraction texte avec pdftotext ou OCR si scan
2. Reconstituer les paragraphes (merger les lignes coupées)
3. Détecter les headers par taille de police ou patterns
4. Extraire les tableaux séparément
5. Ajouter frontmatter YAML

### CSV/JSON → markdown
1. Créer un tableau markdown
2. Si > 100 lignes, découper en fichiers par groupe logique
3. Ajouter frontmatter avec schéma des colonnes

## Frontmatter standard
```yaml
---
source: "URL ou chemin original"
date_collecte: "YYYY-MM-DD"
type: "webpage|pdf|csv|json|doc"
langue: "fr|en"
taille_originale: "X Ko"
---
```

## Nommage des fichiers
`{source_domain}_{titre_slugifié}_{date}.md`
Exemple : `ovhcloud_api-docs_2026-02-22.md`
