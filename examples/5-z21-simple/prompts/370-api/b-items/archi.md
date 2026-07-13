# Sous-contexte : b-items

## Périmètre

CRUD complet sur les items d'un utilisateur.

## Endpoints

| Méthode | Route | Auth | Description |
|---------|-------|------|-------------|
| GET | `/items/` | JWT | Liste les items de l'utilisateur connecté |
| POST | `/items/` | JWT | Crée un item |
| GET | `/items/{id}` | JWT | Détail d'un item (ownership vérifié) |
| PUT | `/items/{id}` | JWT | Met à jour un item (ownership vérifié) |
| DELETE | `/items/{id}` | JWT | Supprime un item (ownership vérifié) |

## Schéma PostgreSQL

```sql
CREATE TABLE items (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    data       JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_items_owner ON items(owner_id);
```

## Fichiers concernés

```
$PROJECT/
├── api/items.py           # Routes FastAPI
├── models/item.py         # Pydantic ItemIn, ItemOut
└── tests/test_b_items.py  # Tests pytest
```

## Modèles Pydantic

```python
class ItemIn(BaseModel):
    name: str
    data: dict = {}

class ItemOut(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    data: dict
    created_at: datetime
    updated_at: datetime
```

## Auth

- `owner_id` = `token["sub"]`
- Sur GET/PUT/DELETE `{id}` : vérifier `item.owner_id == token["sub"]` → 403 sinon
- Ne jamais accepter `owner_id` dans le body

## Règles métier

- `data` accepte n'importe quel JSON valide
- `updated_at` mis à jour automatiquement via trigger PostgreSQL ou dans la requête
