# Sous-contexte : b-users

## Périmètre

Gestion des utilisateurs : lecture du profil courant.

## Endpoints

| Méthode | Route | Auth | Description |
|---------|-------|------|-------------|
| GET | `/users/me` | JWT requis | Retourne le profil de l'utilisateur connecté |
| GET | `/users/{id}` | JWT requis | Retourne un profil public (email masqué) |

## Schéma PostgreSQL

```sql
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

## Fichiers concernés

```
$PROJECT/
├── api/users.py          # Routes FastAPI
├── models/user.py        # Pydantic UserOut, UserPublic
└── tests/test_b_users.py # Tests pytest
```

## Modèles Pydantic

```python
class UserOut(BaseModel):      # GET /users/me
    id: UUID
    email: str
    created_at: datetime

class UserPublic(BaseModel):   # GET /users/{id}
    id: UUID
    created_at: datetime
```

## Auth

- `owner_id` = `token["sub"]` (UUID Keycloak)
- Ne jamais lire l'identité depuis le body

## Notes

- La table `users` est peuplée automatiquement au 1er login Keycloak (hook JWT)
- Pas d'endpoint de création directe (géré par Keycloak)
