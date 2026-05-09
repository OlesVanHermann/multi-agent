# 800 — Methodology

## Analyse d'un bilan
1. Lire le bilan 500 de l'agent infra
2. Identifier : qu'est-ce qui a bien marché, qu'est-ce qui a échoué
3. L'échec vient-il de la methodology ou du system.md ?
   - Si methodology → je corrige
   - Si system.md → je signale à 945 (boucle longue)

## Réécriture d'une methodology
1. Lire la methodology actuelle
2. Identifier la section concernée par l'échec
3. Réécrire cette section avec la leçon apprise
4. Ajouter un changelog en bas du fichier :
```markdown
## Changelog
- {date} : {section modifiée} — {raison} — {résultat attendu}
```

## Règles
- Ne jamais supprimer une règle qui marche pour en ajouter une autre
- Toujours vérifier que le changement ne casse pas autre chose
- Si une methodology dépasse 100 lignes → la simplifier
- Préférer les exemples concrets aux règles abstraites
