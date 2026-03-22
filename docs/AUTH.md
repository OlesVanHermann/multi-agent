# Authentication — Multi-Agent System

## Architecture

```
Internet
    |
    v
nginx :80/:443 (reverse proxy, TLS termination)
    |-- .git, .env, .map → deny all (404)
    |-- Security headers (nosniff, X-Frame, XSS-Protection, Referrer-Policy)
    |
    v
Dashboard :8050 (FastAPI)
    |-- JWT auth middleware: every /api/* requires Bearer token
    |-- WebSocket auth: every /ws/* requires ?token=<JWT>
    |-- CORS whitelist (your-domain.example.com, localhost)
    |-- Keycloak :8080 realm "multi-agent" (JWT issuer + JWKS)
    |
    v
Redis :6379 (requirepass, 127.0.0.1 only)
    |
Agent bridges :9100-10010 (127.0.0.1 only, HEALTH_TOKEN)
```

## Keycloak

- **Instance** : `ma-keycloak` Docker container
- **Port** : 127.0.0.1:8080
- **Realm** : `multi-agent`
- **Client** : `multi-agent-web` (public, direct access grants)
- **Admin credentials** : `setup/secrets.cfg` → `KEYCLOAK_ADMIN_PASSWORD`
- **Mode** : production (`start`, not `start-dev`)

### Users

| Username | Role | Purpose |
|----------|------|---------|
| dev1 | admin | Full access |
| dev2 | operator | Operator access |

### Password management

```bash
./setup/keycloak_user_list.sh                               # List users
./setup/keycloak_user_create.sh <username> <password> <email>  # Create user
./setup/keycloak_user_delete.sh <username>                   # Delete user
```

Scripts read credentials from `setup/secrets.cfg` automatically.

## Dashboard API Auth

**Middleware** : `web/backend/server.py` → `auth_middleware`

### HTTP API

- ALL `/api/*` routes require `Authorization: Bearer <JWT>` header
- Zero public API endpoints (including `/api/health`)
- `/auth/*` routes proxied to Keycloak (public, for login flow)
- Static frontend files are public (no API data)

### WebSocket

- ALL `/ws/*` routes require `?token=<JWT>` query param
- Token verified before `websocket.accept()` — rejected with code 1008 if invalid
- Endpoints: `/ws/agent/{id}`, `/ws/status`, `/ws/messages`

### CORS

```python
allow_origins=[
    "https://your-domain.example.com",
    "https://other-subdomain.example.com",
    "http://localhost:5173",
    "http://localhost:8050",
]
allow_credentials=True
```

Only whitelisted origins.

## JWT Validation

**File** : `web/backend/server.py` → `_verify_jwt_minimal()`

Two-tier validation:

1. **Primary** : `pyjwt.decode()` with `PyJWKClient` (JWKS from Keycloak)
   - Fetches public keys from `http://localhost:8080/realms/multi-agent/protocol/openid-connect/certs`
   - Verifies RS256 signature (cryptographic proof)
   - Checks expiration (`exp`)
   - Checks issuer contains `/realms/multi-agent`
   - Keys cached 1 hour

2. **Fallback** (if JWKS unreachable) : payload-only check
   - Rejects unsigned tokens (`alg:none`, empty signature)
   - Checks expiration and issuer
   - Less secure but prevents total lockout if Keycloak is temporarily down

### Issuer matching

Tokens may have internal (`http://localhost:8080/realms/multi-agent`) or external
(`https://your-domain.example.com/realms/multi-agent`) issuer URL. Both accepted as long as
`/realms/multi-agent` is present and the signature is valid.

## Frontend Auth

**File** : `web/frontend/src/AuthProvider.jsx`

### Login flow

1. User submits username/password on login form
2. Frontend POSTs to Keycloak token endpoint (grant_type=password)
3. Keycloak returns `access_token` + `refresh_token`
4. Tokens stored in `localStorage`
5. Auto-refresh scheduled 60s before expiration

### Token injection

- `App.jsx` monkey-patches `window.fetch` to inject `Authorization: Bearer` on all `/api/*` calls
- `basePath.js` appends `?token=<JWT>` to all WebSocket URLs
- On 401 response or refresh failure → session cleared, login form shown

## Input Validation

- Agent ID: regex `^\d{3}(-\d{3})?$`
- Agent input text: non-printable characters blocked (prevents tmux escape injection)
- File paths: `..` and null bytes blocked, symlinks checked against allowed directories
- Agent names: HTML-escaped to prevent XSS

## Security Headers

Applied by middleware on every response:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`

## Redis

- **Instance** : `ma-redis` Docker container
- **Port** : 127.0.0.1:6379 (local only)
- **Auth** : `requirepass` (password in `setup/secrets.cfg` → `REDIS_PASSWORD`)
- **Prefix** : `A:` for all multi-agent keys

## Agent Bridge Health Endpoints

Each bridge exposes a health HTTP server on ports 9100-10010.

- **Bind** : 127.0.0.1 (not accessible from internet)
- **Auth** : `HEALTH_TOKEN` required (query param or Bearer header)
- **Default** : reject all if `HEALTH_TOKEN` env var not set (secure by default)
- **Endpoint** : `GET /health?token=<HEALTH_TOKEN>`

Without token → 401. Wrong token → 401. No token configured → 401.

## Network

### Ports exposed (0.0.0.0)

| Port | Service | Auth |
|------|---------|------|
| 22 | SSH | SSH keys |
| 80/443 | nginx | Proxy to backend (JWT auth) |

### Ports local only (127.0.0.1)

| Port | Service | Auth |
|------|---------|------|
| 6379 | Redis | requirepass |
| 8050 | Dashboard | Keycloak JWT |
| 8080 | Keycloak | Admin password |
| 9100-10010 | Agent bridges | HEALTH_TOKEN |

### nginx

```nginx
location ~ /\.git { deny all; }
location ~ /\.env { deny all; }
location ~ \.map$  { deny all; }
```

### Docker

- `docker-compose.yml` reads `KEYCLOAK_ADMIN_PASSWORD` from env (not hardcoded)
- Keycloak runs in production mode (`start`, not `start-dev`)
- All Docker ports bound to 127.0.0.1
