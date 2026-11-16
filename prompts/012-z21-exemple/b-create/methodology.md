# b-create Methodology

## Avant de coder
1. Lire `archi.md` — vérifier les noms de colonnes exacts
2. Confirmer le nom de colonne `owner_id` : `SELECT column_name FROM information_schema.columns WHERE table_name='todos'`

## Points d'attention
- `owner_id` = `user["sub"]` depuis le token. JAMAIS depuis le body.
- `title` doit être validé non-vide côté Pydantic (min_length=1)
- Retourner HTTP 422 si validation échoue (comportement FastAPI par défaut)

## Tests
```bash
cd $BASE && python -m pytest tests/test_todos_create.py -v
```

## Checklist pre-commit
- [ ] `owner_id` extrait du token
- [ ] Validation `title` présente
- [ ] Test passent
- [ ] `git commit -m "feat(b-create): {description}"`
