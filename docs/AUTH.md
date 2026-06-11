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
Dashboard :8050 (FastAPI — web/backend/multi_agent/, assemblé par server.py)
    |-- /auth/*  : proxy vers Keycloak — pose les jetons en cookies HttpOnly (B3)
    |-- /api/*   : JWT obligatoire (header Bearer ou cookie) + rate limit (B5)
    |-- /ws/*    : ticket à usage unique ou cookie — jamais de JWT en URL (B4)
    |-- CORS whitelist + anti-CSRF double-submit
    |
    v
Keycloak :8080 realm "multi-agent" (issuer + JWKS)
Redis :6379 (requirepass, 127.0.0.1 only)
Agent bridges :9100+ (127.0.0.1 only, HEALTH_TOKEN)
```

Le frontend ne voit **jamais** les jetons : pas de `localStorage`, pas de
`?token=` en query string.

## Keycloak

- **Instance** : conteneur Docker `ma-keycloak` (version épinglée, C2)
- **Port** : 127.0.0.1:8080 (`KEYCLOAK_URL`)
- **Realm** : `multi-agent` (`KEYCLOAK_REALM`)
- **Client** : `multi-agent-web` (`KEYCLOAK_CLIENT_ID`)
- **Secrets** : `setup/secrets.cfg` (jamais versionné — voir
  `setup/secrets.cfg.template`)
- Gestion des comptes : `setup/keycloak_user_create.sh`,
  `keycloak_user_list.sh`, `keycloak_passwd_modify.sh`,
  `keycloak_user_delete.sh`

## Login (B3 — cookies HttpOnly)

Le navigateur ne parle jamais directement à Keycloak : le backend expose un
proxy `/auth/{path}` restreint aux endpoints OIDC du realm
(`/realms/multi-agent/protocol/openid-connect/…`, `/.well-known/…` ;
`/admin` refusé).

Sur un `POST …/token` réussi, le backend :

1. pose `ma_access` (access token) en cookie **HttpOnly**, `path=/`,
   `SameSite=Strict`, `Secure` derrière HTTPS ;
2. pose `ma_refresh` (refresh token) en cookie **HttpOnly**, `path=/auth` ;
3. pose `ma_csrf` (aléa) en cookie **non HttpOnly** — le JS le relit pour le
   double-submit anti-CSRF ;
4. renvoie un corps **sans jetons** (juste `expires_in` + profil utilisateur).

Refresh et logout : le JS appelle `/auth/...` sans connaître le refresh
token ; le backend l'injecte depuis le cookie `ma_refresh`. Le logout efface
les trois cookies.

### Anti-CSRF (double-submit)

Quand l'auth provient du cookie (envoyé automatiquement par le navigateur),
toute requête mutative (`POST/PUT/PATCH/DELETE`) sur `/api/*` doit porter le
header `X-CSRF-Token` égal au cookie `ma_csrf`, sinon 403.

## Vérification JWT (B2 — stricte)

`_verify_jwt_minimal` (`web/backend/multi_agent/auth.py`), via **PyJWT** +
`PyJWKClient` (cache JWKS 3600 s) :

- **Signature** : RS256 contre les clés publiques du realm (JWKS) ;
- **Issuer strict** : égalité exacte avec
  `{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}` (un suffixe du type
  `…/realms/multi-agent.evil.com` est rejeté) ;
- **Audience** : `multi-agent-web` doit figurer dans `aud` **ou** dans `azp`
  (les clients publics Keycloak sans mapper d'audience mettent le client ID
  dans `azp`) ;
- **Expiration** vérifiée ; tout échec ⇒ 401.

Ordre d'extraction du jeton : header `Authorization: Bearer …` d'abord,
cookie `ma_access` sinon. Aucun jeton accepté en query string.

Chemins publics (sans auth) : `/api/agent-chat/health`,
`/api/agent-chat/spec`, et les préfixes `/auth/`, `/assets/`, `/favicon`.

## WebSocket (B4 — ticket à usage unique)

Le JWT ne transite jamais en URL (les `?token=` finissent dans les access
logs nginx/proxies). À la place :

1. le client (déjà authentifié) appelle `POST /api/ws-ticket` →
   `{"ticket": "...", "expires_in": 30}` (stocké dans Redis, TTL 30 s) ;
2. il ouvre `wss://…/ws/agent/300?ticket=<ticket>` ;
3. le backend valide **et invalide** le ticket (DEL atomique → non
   rejouable). Fallback : cookie `ma_access` (vérification JWT complète).

L'Origin est contrôlé contre la whitelist CORS.

### Codes de fermeture WS

| Code | Signification |
|------|---------------|
| 4001 | JWT/ticket invalide ou absent |
| 4002 | Rate limit dépassé (`/ws/agent`) |
| 4005 | Agent 000 interdit en streaming |
| 1008 | Violation de policy (origin, format d'agent_id, limite sur `/ws/status` et `/ws/messages`) |
| 1013 | Serveur saturé (max connexions) |

## Rate limiting (B5 — partagé Redis)

300 requêtes / 60 s par IP (`web/backend/multi_agent/ratelimit.py`),
compteur **partagé entre workers** dans Redis
(`{MA_PREFIX}:ratelimit:{ip}`), avec fallback local par process si Redis est
indisponible. Appliqué :

- sur toutes les requêtes `/api/*` (HTTP 429) ;
- à l'ouverture des WebSockets (close 4002 / 1008), avant origin et auth.

## Tests

```bash
python -m pytest tests/test_jwt_verification.py -v   # B2/G2 : issuer, audience, exp, signature
python -m pytest tests/test_auth_cookies.py -v       # B3
python -m pytest tests/test_ws_ticket.py -v          # B4
python -m pytest tests/test_rate_limit_redis.py -v   # B5/G2 : compteur partagé + codes WS
```
