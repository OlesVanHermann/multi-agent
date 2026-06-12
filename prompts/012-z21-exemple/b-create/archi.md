# b-create — Architecture

## Scope
Création de todos via `POST /todos`.
Validation des champs, insertion en base, retour de l'objet créé.

## Fichiers

| Fichier | Lignes | Rôle |
|---------|--------|------|
| `todos_api.py` | L1-80 | Endpoint POST + validation |
| `todos_schema.sql` | L1-20 | Schéma table todos |

## API exposée

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/todos` | Créer un todo |

## Schéma

```sql
CREATE TABLE todos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    done BOOLEAN NOT NULL DEFAULT FALSE,
    owner_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

## Pattern technique

```python
@router.post("/todos", response_model=TodoOut)
async def create_todo(
    body: TodoCreate,
    user: dict = Depends(get_current_user)
):
    owner_id = user["sub"]  # JAMAIS depuis body
    return await db.insert_returning("todos", {...})
```

## Attention
- `owner_id` vient TOUJOURS du token (`user["sub"]`), jamais du body
- Valider `title` non vide avant insertion
