# 200-500 — Methodology

## Étapes
1. Lister les fichiers dans project/raw/
2. Lister les fichiers dans project/clean/
3. Vérifier la couverture (raw → clean)
4. Pour chaque fichier clean :
   - Vérifier le frontmatter YAML
   - Vérifier l'absence de boilerplate
   - Vérifier l'encodage UTF-8
5. Calculer les scores par métrique
6. Écrire dans `bilans/200-cycle{N}.md`
7. Publier `bilans:ready`
