# b-list Methodology

## Avant de coder
1. Vérifier que le filtre `owner_id` est bien présent dans toutes les requêtes SELECT
2. Confirmer le nom exact de la colonne : `SELECT column_name FROM information_schema.columns WHERE table_name='todos'`

## Points d'attention
- Isolation multi-tenant : chaque GET doit filtrer par `owner_id = user["sub"]`
- Si filtre `owner_id` absent → fuite de données (bug critique)
- Pagination optionnelle : `limit` + `offset` si liste potentiellement longue

## Tests
```bash
cd $BASE && python -m pytest tests/test_todos_list.py -v
```

## Checklist pre-commit
- [ ] `owner_id` dans tous les filtres SELECT
- [ ] Test d'isolation (user A ne voit pas les todos de user B)
- [ ] Tests passent
- [ ] `git commit -m "feat(b-list): {description}"`
