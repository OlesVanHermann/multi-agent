# Methodology — b-items

## Pattern d'implémentation

### Vérification d'ownership

```python
async def get_item_or_403(item_id: UUID, user_id: str, db) -> dict:
    row = await db.fetchrow("SELECT * FROM items WHERE id=$1", item_id)
    if not row:
        raise HTTPException(404, "Item not found")
    if str(row["owner_id"]) != user_id:
        raise HTTPException(403, "Forbidden")
    return dict(row)
```

### Route POST /items/

```python
@router.post("/items/", response_model=ItemOut, status_code=201)
async def create_item(body: ItemIn, token=Depends(get_current_user), db=Depends(get_db)):
    owner_id = token["sub"]
    row = await db.fetchrow(
        "INSERT INTO items(owner_id, name, data) VALUES($1,$2,$3) RETURNING *",
        owner_id, body.name, Json(body.data)
    )
    return ItemOut(**dict(row))
```

### Route DELETE /items/{id}

```python
@router.delete("/items/{item_id}", status_code=204)
async def delete_item(item_id: UUID, token=Depends(get_current_user), db=Depends(get_db)):
    await get_item_or_403(item_id, token["sub"], db)
    await db.execute("DELETE FROM items WHERE id=$1", item_id)
```

## Pattern de test

```python
async def test_create_item(client, mock_token):
    r = await client.post("/items/", json={"name": "test", "data": {}}, headers=auth_headers(mock_token))
    assert r.status_code == 201
    assert r.json()["name"] == "test"

async def test_delete_other_user_item(client, mock_token, other_token):
    # Créer avec other_token, supprimer avec mock_token → 403
    r = await client.post("/items/", json={"name": "x"}, headers=auth_headers(other_token))
    item_id = r.json()["id"]
    r2 = await client.delete(f"/items/{item_id}", headers=auth_headers(mock_token))
    assert r2.status_code == 403
```

## Règles apprises

_(vide au démarrage — le Coach ajoute ici si un pattern d'erreur apparaît 3x)_
