# b-list — Architecture

## Scope
Lecture et filtrage de todos via `GET /todos`.
Retourne uniquement les todos de l'utilisateur connecté (isolation multi-tenant).

## Fichiers

| Fichier | Lignes | Rôle |
|---------|--------|------|
| `todos_api.py` | L81-150 | Endpoint GET + filtrage |

## API exposée

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/todos` | Lister mes todos |
| GET | `/todos?done=true` | Filtrer par statut |

## Pattern technique

```python
@router.get("/todos", response_model=list[TodoOut])
async def list_todos(
    done: bool | None = None,
    user: dict = Depends(get_current_user)
):
    owner_id = user["sub"]
    filters = {"owner_id": owner_id}
    if done is not None:
        filters["done"] = done
    return await db.select("todos", filters)
```

## Attention
- Filtrer TOUJOURS par `owner_id` — isolation stricte entre utilisateurs
- Ne jamais retourner les todos d'un autre utilisateur
