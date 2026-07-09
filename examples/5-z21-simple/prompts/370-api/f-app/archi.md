# Sous-contexte : f-app

## Périmètre

Frontend React : authentification Keycloak + affichage des items.

## Structure des fichiers

```
$PROJECT/src/
├── main.jsx                  # Point d'entrée, ReactKeycloakProvider
├── App.jsx                   # Router + layout
├── keycloak.js               # Instance Keycloak
├── api/
│   └── client.js             # axios + intercepteur JWT
├── hooks/
│   ├── useAuth.js            # token, user, logout
│   └── useItems.js           # CRUD items via API
├── pages/
│   ├── HomePage.jsx          # Liste des items
│   └── ItemDetailPage.jsx    # Détail + édition
└── components/
    ├── ItemCard.jsx
    ├── ItemForm.jsx
    └── NavBar.jsx
```

## Dépendances

```json
{
  "keycloak-js": "^24.0.0",
  "@react-keycloak/web": "^3.4.0",
  "axios": "^1.6.0",
  "react-router-dom": "^6.0.0"
}
```

## Auth flow

1. `keycloak.js` : instance avec `url`, `realm`, `clientId` depuis `import.meta.env`
2. `main.jsx` : `<ReactKeycloakProvider>` enveloppe tout
3. `client.js` : intercepteur ajoute `Authorization: Bearer ${token}`
4. `useAuth.js` : expose `{ token, user, isAuthenticated, logout }`

## Variables d'environnement

```
VITE_API_URL=http://localhost:8000
VITE_KC_URL=http://localhost:8080
VITE_KC_REALM=multi-agent
VITE_KC_CLIENT=frontend
```

## Règles

- Ne jamais stocker le token en localStorage (géré par keycloak-js)
- Toujours utiliser `keycloak.updateToken(30)` avant les appels API
- Routes protégées : redirect vers Keycloak si `!isAuthenticated`
