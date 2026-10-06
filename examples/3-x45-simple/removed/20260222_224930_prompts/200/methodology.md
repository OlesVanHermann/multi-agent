# 200 — Methodology

## Étapes
1. Lire `project/raw/ventes-2025.csv`
2. Parser les headers et détecter les types (string, int, float, date)
3. Écrire le frontmatter YAML :
   ```yaml
   ---
   source: ventes-2025.csv
   colonnes: [date, produit, region, quantite, prix_unitaire, total]
   lignes: {nb}
   types: {date: date, produit: string, ...}
   ---
   ```
4. Convertir en tableau markdown avec alignement
5. Écrire dans `project/clean/ventes-2025.md`
6. Publier `data:cleaned` sur Redis
