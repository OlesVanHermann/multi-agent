# Methodology — b-users

## Pattern d'implémentation

### Route GET /users/me

```python
@router.get("/users/me", response_model=UserOut)
async def get_me(token: dict = Depends(get_current_user), db=Depends(get_db)):
    user_id = token["sub"]
    row = await db.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
    if not row:
        raise HTTPException(404, "User not found")
    return UserOut(**dict(row))
```

### Route GET /users/{id}

```python
@router.get("/users/{user_id}", response_model=UserPublic)
async def get_user(user_id: UUID, db=Depends(get_db)):
    row = await db.fetchrow("SELECT id, created_at FROM users WHERE id=$1", user_id)
    if not row:
        raise HTTPException(404, "User not found")
    return UserPublic(**dict(row))
```

## Pattern de test

```python
async def test_get_me(client, mock_token):
    response = await client.get("/users/me", headers=auth_headers(mock_token))
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert "email" in data

async def test_get_me_unauthorized(client):
    response = await client.get("/users/me")
    assert response.status_code == 401
```

## Règles apprises

_(vide au démarrage — le Coach ajoute ici si un pattern d'erreur apparaît 3x)_
