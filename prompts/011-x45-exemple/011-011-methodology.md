# 011-011 Methodology — Dev

## Avant de coder
1. Lire `memory.md` — identifier le fichier source et la transformation attendue
2. Vérifier que le fichier source existe : `ls -la {fichier_source}`
3. Comprendre les critères de succès définis dans memory.md

## Exécution
1. `mkdir -p $BASE/pipeline/011-output/`
2. Lire le fichier source intégralement
3. Appliquer la transformation
4. Écrire le résultat

## Points d'attention
- Respecter exactement les critères de succès de memory.md
- Si ambiguïté : choisir l'interprétation la plus stricte
- Ne pas ajouter de contenu non demandé

## Checklist pre-commit
- [ ] Fichier créé dans `pipeline/011-output/`
- [ ] `wc -l` non vide
- [ ] `git status` propre
- [ ] `git commit` fait avant d'envoyer DONE
