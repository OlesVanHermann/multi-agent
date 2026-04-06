# 600 — Methodology

## Chunking
1. Lire le fichier markdown
2. Découper par sections (## headers)
3. Si une section > 500 tokens, découper par paragraphes
4. Si un paragraphe > 500 tokens, découper par phrases
5. Chaque chunk conserve le titre du fichier + le header de section comme préfixe
6. Overlap de 50 tokens entre chunks consécutifs

## Embedding
- Modèle : bge-m3 (local, multilingue)
- Normaliser les vecteurs (L2 norm = 1)
- Stocker : vecteur + texte chunk + métadonnées source

## Stockage index
```json
{
  "chunks": [
    {
      "id": "chunk_001",
      "text": "contenu du chunk",
      "embedding": [0.01, -0.03, ...],
      "source_file": "project/clean/xxx.md",
      "source_section": "## Titre section",
      "metadata": {
        "source": "URL originale",
        "date": "2026-02-22",
        "type": "webpage",
        "langue": "fr"
      }
    }
  ]
}
```

## Mise à jour incrémentale
- Écouter `data:cleaned` sur Redis
- Lire manifest.json pour identifier les nouveaux fichiers
- Indexer uniquement les nouveaux (comparer avec index-meta.json)
- Publier `index:updated` une fois terminé

## Moteur de recherche
Exposer une fonction `search(query, top_k=10)` :
1. Embed la query avec bge-m3, input_type="query"
2. Cosine similarity contre tous les chunks
3. Retourner les top_k avec score + texte + métadonnées
