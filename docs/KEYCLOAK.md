# Keycloak — Authentification Multi-Agent

## Vue d'ensemble

Keycloak est **obligatoire** pour l'authentification du dashboard. Il n'y a pas de fallback.
Si Keycloak est down, le login retourne HTTP 503.

```
Frontend (React)
    │
    ├─► LoginForm (username/password)
    │       │
    │       └─► POST /auth/realms/multi-agent/protocol/openid-connect/token
    │               ↓
    │           Backend Proxy (FastAPI)
    │               ↓
    │           Keycloak (localhost:8080)
    │               ↓
    │           { access_token, refresh_token, expires_in }
    │
    ├─► JWT décodé → { preferred_username, email, name, roles }
    │
    ├─► Auto-refresh 60s avant expiration
    │   └─► Keycloak 503 → retry 30s
    │
    └─► Session persistée en localStorage
```

---

## Installation

```bash
./setup/install_keycloak.sh
```

Ce script :
1. Installe Docker si absent (Mac via Homebrew+Colima, Linux via apt)
2. Lance le container Keycloak 23.0 (`start-dev`)
3. Importe le realm depuis `web/keycloak/realm-multi-agent.json`
4. Configure les scopes `profile` et `email` avec les mappers JWT
5. Vérifie le health check (`/health/ready`)

**Port** : `127.0.0.1:8080` (localhost uniquement)

---

## Gestion des utilisateurs

```bash
# Créer un utilisateur
./setup/keycloak_user_create.sh <username> <password>

# Lister les utilisateurs
./setup/keycloak_user_list.sh

# Changer un mot de passe
./setup/keycloak_passwd_modify.sh <username> <new-password>

# Supprimer un utilisateur
./setup/keycloak_user_delete.sh <username>
```

### Utilisateurs par défaut (realm import)

| Username | Email | Rôle | Password |
|----------|-------|------|----------|
| `octave` | octave@multi-agent.local | admin | `changeme` (temporaire) |
| `operator` | operator@multi-agent.local | operator | `operator123` (temporaire) |
| `viewer` | viewer@multi-agent.local | viewer | `viewer123` (temporaire) |

---

## Rôles

| Rôle | Permissions |
|------|------------|
| **admin** | Tout : view, send, restart, kill |
| **operator** | View + send commands |
| **viewer** | Read only |

Hiérarchie dans le frontend : `admin` > `operator` > `viewer`

```javascript
isAdmin()    // admin
isOperator() // operator || admin
isViewer()   // viewer || operator || admin
```

---

## Configuration du realm

**Fichier** : `web/keycloak/realm-multi-agent.json`

### Client

| Paramètre | Valeur |
|-----------|--------|
| Client ID | `multi-agent-web` |
| Type | Public (pas de secret) |
| Grant types | `password`, `refresh_token` |
| Standard Flow | Oui |
| Redirect URIs | `*` |

### Client Scopes (JWT claims)

Le JWT doit contenir `preferred_username`, `email`, `name` et `roles`.
Ces claims sont injectés via les **client scopes** définis dans le realm :

| Scope | Mappers | Claims dans le JWT |
|-------|---------|-------------------|
| `roles` | realm-role-mapper | `roles` (array) |
| `profile` | preferred_username, full name | `preferred_username`, `name` |
| `email` | email | `email` |

**Important** : sans les scopes `profile` et `email` explicitement définis avec `"access.token.claim": "true"`, le JWT ne contient pas `preferred_username` et le username ne s'affiche pas dans le frontend.

Le script `install_keycloak.sh` configure ces scopes automatiquement après l'installation.

---

## Token refresh

Géré automatiquement par `AuthProvider.jsx` :

| Paramètre | Valeur | Description |
|-----------|--------|-------------|
| Expiration JWT | 300s (5 min) | Défaut Keycloak |
| Refresh margin | 60s | Refresh 60s avant expiration → à ~240s |
| Minimum delay | 10s | Pas de refresh avant 10s |
| Retry on 503 | 30s | Si Keycloak down |
| Refresh token expiré | Logout | Force re-login |

**Cycle** :
1. Login → JWT (5 min) + refresh token
2. À 4 min → auto-refresh via `refresh_token`
3. Nouveau JWT (5 min) + nouveau refresh token
4. Boucle infinie tant que Keycloak est up

---

## Architecture

### Docker Compose

```yaml
keycloak:
  image: quay.io/keycloak/keycloak:23.0
  environment:
    - KEYCLOAK_ADMIN=admin
    - KEYCLOAK_ADMIN_PASSWORD=admin
    - KC_HEALTH_ENABLED=true
  command: start-dev --import-realm
  volumes:
    - ./keycloak/realm-multi-agent.json:/opt/keycloak/data/import/realm-multi-agent.json:ro
    - keycloak_data:/opt/keycloak/data
  ports:
    - "127.0.0.1:8080:8080"
```

### Proxy backend (FastAPI)

Le frontend appelle `/auth/*`, le backend proxy vers Keycloak :

```python
@app.api_route("/auth/{path:path}", methods=["GET","POST","PUT","DELETE","OPTIONS"])
async def proxy_keycloak(request, path):
    url = f"{KEYCLOAK_URL}/{path}"  # KEYCLOAK_URL = http://localhost:8080
    # Forward request, return 503 if Keycloak unreachable
```

### Nginx (production Docker)

```nginx
location /auth/ {
    proxy_pass http://keycloak/;
}
```

---

## Persistance des données

Les données utilisateurs sont dans le **volume Docker `keycloak_data`** (ou `ma-keycloak-data` via install_keycloak.sh).

- Un `git pull` ou upgrade **ne les écrase pas**
- Le realm import (`--import-realm`) ne réimporte que si le realm n'existe pas encore
- Pour réinitialiser : supprimer le volume Docker

```bash
# Voir le volume
docker volume ls | grep keycloak

# Réinitialiser (PERD TOUS LES USERS)
docker volume rm ma-keycloak-data
./setup/install_keycloak.sh
```

---

## API Keycloak (référence)

### Endpoints publics (OAuth2)

```bash
# Login (password grant)
curl -X POST http://localhost:8080/realms/multi-agent/protocol/openid-connect/token \
  -d "grant_type=password&client_id=multi-agent-web&username=octave&password=changeme"

# Refresh token
curl -X POST http://localhost:8080/realms/multi-agent/protocol/openid-connect/token \
  -d "grant_type=refresh_token&client_id=multi-agent-web&refresh_token=<TOKEN>"

# Health check
curl -s http://localhost:8080/health/ready
```

### Admin REST API (nécessite token admin)

```bash
# Obtenir un token admin
TOKEN=$(curl -s -X POST http://localhost:8080/realms/master/protocol/openid-connect/token \
  -d "grant_type=password&client_id=admin-cli&username=admin&password=admin" | jq -r .access_token)

# Lister les users
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/admin/realms/multi-agent/users

# Créer un user
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  http://localhost:8080/admin/realms/multi-agent/users \
  -d '{"username":"newuser","enabled":true,"credentials":[{"type":"password","value":"pass","temporary":false}]}'

# Changer password
curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  http://localhost:8080/admin/realms/multi-agent/users/<USER_ID>/reset-password \
  -d '{"type":"password","value":"newpass","temporary":false}'
```

---

## Troubleshooting

### Le username ne s'affiche pas dans le header

**Cause** : les scopes `profile`/`email` ne sont pas définis dans `clientScopes` du realm, ou n'ont pas `"access.token.claim": "true"`.

**Fix** : relancer `./setup/install_keycloak.sh` (configure les scopes automatiquement).

Ou vérifier manuellement :
```bash
# Décoder le JWT pour voir les claims
echo "<access_token>" | cut -d. -f2 | base64 -d 2>/dev/null | jq .
# Doit contenir: preferred_username, email, name, roles
```

### Keycloak 503 au login

**Cause** : Keycloak n'est pas démarré.

```bash
docker ps | grep keycloak          # Container tourne ?
curl -s http://localhost:8080/health/ready  # Prêt ?
./setup/install_keycloak.sh    # Relancer si nécessaire
```

### Token expiré, pas de refresh

**Cause** : version simplifiée de AuthProvider sans auto-refresh.

**Fix** : vérifier que `AuthProvider.jsx` contient `REFRESH_MARGIN_S`, `refreshAccessToken()`, et `applyTokens()`.

### Realm non importé

**Cause** : le realm existe déjà dans le volume → Keycloak ne réimporte pas.

```bash
# Supprimer et recréer
docker stop ma-keycloak && docker rm ma-keycloak
docker volume rm ma-keycloak-data
./setup/install_keycloak.sh
```

---

## Valeurs de référence

| Paramètre | Valeur |
|-----------|--------|
| Image | `quay.io/keycloak/keycloak:23.0` |
| Port | `127.0.0.1:8080` |
| Admin | `admin` / `admin` |
| Realm | `multi-agent` |
| Client ID | `multi-agent-web` |
| Mode | `start-dev` (développement) |
| Health | `GET /health/ready` |
| Volume | `ma-keycloak-data` ou `keycloak_data` |
| Proxy timeout | 30s (backend FastAPI) |
| JWT expiration | 300s (défaut Keycloak) |
| Refresh margin | 60s avant expiration |
