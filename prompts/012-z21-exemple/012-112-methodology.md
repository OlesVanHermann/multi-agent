# 012-112 Methodology — Dev z21

## Avant de coder
1. Lire `{ctx}/archi.md` intégralement
2. Lire `{ctx}/memory.md` — bugs connus, état
3. Lire `{ctx}/methodology.md` — checklist spécifique

## Points d'attention
- Vérifier les noms de colonnes réels via `information_schema` si DB impliquée
- Ne jamais extraire user/sender depuis le body — toujours depuis le token
- Un git commit AVANT d'envoyer DONE au Master

## Checklist pre-commit
- [ ] Fichiers modifiés correspondent à `archi.md`
- [ ] Tests existants toujours verts
- [ ] `git status` propre
- [ ] `git commit` avec message `feat({ctx}): {description}`
