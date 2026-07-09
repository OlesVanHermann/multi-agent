# 170 — Reference : Decoupage en sous-contextes

## Principe

Le decoupage est la phase la plus critique. Un mauvais decoupage genere des allers-retours inutiles entre contextes et des bugs de scope.

---

## LECONS DE PRODUCTION — Patterns critiques

Ces patterns ont ete decouverts en production sur les premiers z21. Les integrer systematiquement dans chaque nouveau z21.

### 1. asyncpg JSONB double-encoding (CRITIQUE)
Passer une Python list/dict pour `$1::jsonb`, JAMAIS `json.dumps(value)`. Le codec asyncpg fait deja `json.dumps`. Un double-encoding produit une string `'"[\"x\"]"'` au lieu d'un array `["x"]`.
**Impact** : fuite multi-tenancy silencieuse (containment `@>` ne matche plus).

### 2. owner vs owner_id — verifier les colonnes REELLES
Les noms de colonnes varient d'une table a l'autre (`owner` vs `owner_id`). TOUJOURS verifier via `SELECT column_name FROM information_schema.columns WHERE table_name='xxx'` avant d'ecrire un insert_returning.
**Impact** : `asyncpg.UndefinedColumnError` en production.

### 3. _get_username() / _username() pattern varie
Chaque module peut utiliser un pattern different (`user.get("username")` vs `user.get("preferred_username") or user.get("sub")`). Le MOCK_USER dans les tests doit contenir TOUTES les cles (`sub`, `username`, `preferred_username`, `email`).

### 4. _table_ready global flag varie
Nom du flag (`_table_ready` vs `_tables_ready` vs `_initialized`) varie selon le module. Toujours lire le source pour le nom exact. Reset obligatoire dans les tests.

### 5. Sender from token ONLY
JAMAIS accepter sender/username depuis le request body. Si un Pydantic model a un champ `username` ou `sender` → le supprimer, extraire du token.

### 6. Zero-fallback obligatoire
`.get("owner_id", "local")` ou `or "default"` masque un bug multi-tenant. Si absent → erreur explicite, pas de comportement silencieux.

### 7. Git commit avant DONE
Tout fichier modifie DOIT etre commite AVANT de signaler DONE au Master. Verifier `git status` : zero fichier untracked avant `$BASE/scripts/send.sh`.

### 8. Dispatch parallele Dev+Tester
Quand le Reviewer retourne BLOCANTS CODE + BLOCANTS TEST independants, le Master peut dispatcher Dev et Tester en parallele. Gain de temps significatif.

### 9. XADD stream name copy-paste
TOUJOURS copier-coller les stream names depuis le template. JAMAIS taper de memoire. `A:agent:{ID}-1{XX}:inbox` (avec prefixe z21) ≠ `A:agent:1{XX}:inbox` (perte du message).

### 10. Cross-cutting = sous-contexte dedie
Quand une tache touche `_username()` ou `_check_member()` sur 3+ fichiers backend, creer un contexte dedie (`b-features-endpoints`) plutot que dispatcher vers chaque contexte individuellement.

### 11. Auth existante — NE PAS reimplementer
Si le projet a deja un middleware d'auth (JWT Bearer + JWKS Keycloak), un nouveau z21 n'a JAMAIS besoin de reimplementer l'auth. Utiliser les helpers existants (ex: `Depends(get_current_user)`, `create_app()`). Voir la doc AUTH du projet pour le flow complet.

### 12. Routes publiques — whitelist explicite
Les routes publiques (health checks, webhooks, auth proxy) doivent etre whitelistees explicitement dans le middleware. Tout `/api/*` sans Bearer → 401. Si un nouveau service a besoin d'un endpoint public, l'ajouter a la liste des prefixes publics du middleware.

---

## Regles de decoupage

- **Par domaine fonctionnel**, pas par fichier
- Convention : `b-*` pour backend, `f-*` pour frontend
- Granularite fine : 1 contexte = 1 responsabilite claire (pas "tout le CRUD")
- Un fichier backend de 500+ lignes → probablement 3-5 contextes
- Chaque endpoint group logique = 1 contexte
- MCP server = 1 contexte dedie
- Schema PG/microservice-schema = 1 contexte dedie (inclure server_common, ports, health checks)
- Auth/Keycloak = 1 contexte si l'agent a ses propres patterns auth
- Frontend : 1 contexte par panel principal + 1 par hook complexe
- **Cross-cutting** : si auth/membership touche 3+ fichiers backend → creer `b-features-endpoints` dedie (pas dispatcher vers chaque contexte)
- **Overlap cross-z21** : si un module existe dans un autre z21, documenter l'overlap dans master memory (ex: "b-events-sse overlap avec {autre_z21_ID}-{autre_z21_nom}")

---

## Exemples de decoupages reussis

- **Drive (61 ctx)** : b-crud, b-copy-move, b-trash, b-star-hide, b-downloads, b-thumbnail-gen, b-sharing-links, b-sharing-permissions, f-file-browser, f-folder-tree, f-upload, etc.
- **Mail (88 ctx)** : b-imap-connect, b-imap-read, b-imap-flags, b-send, b-reply-forward, b-draft, b-folders, b-attach-upload, f-mail-layout, f-mail-compose, f-mail-reader, etc.
- **Chat (10 ctx)** : streaming_sse, sessions_crud, messages_history, mcp_server, frontend_hooks, markdown_render, etc.
- **Greffier+Transfer (21 ctx)** : b-greffier-upload, b-greffier-worker, b-greffier-convert, b-transfer-stage, b-transfer-task-ready, b-events-sse, etc.
- **Search (15 ctx)** : b-staan-proxy, b-fts-email, b-fts-drive, b-fts-messages, b-docs-federated, b-history-settings, b-workspace, b-filters-recent, b-mcp-server, b-microservice-schema, f-search-panel, f-use-search-engine, f-use-saas-search, f-maps-tab, f-mcp-bridge
- **Framework (19 ctx)** : b-auth-keycloak, b-auth-session, b-logs-ingest, b-logs-query, b-logs-rotation, b-logs-syslog, b-bandwidth, b-transfer-stage, b-transfer-task-ready, b-transfer-download, b-events-sse, b-tasks-crud, b-tasks-reaper, b-server-common-schema, f-keycloak-provider, f-logger, f-logs-panel, f-transfer-ui, f-events-hook
- **Messaging (12 ctx)** : b-channels, b-messages, b-search, b-contacts, b-multi-tenancy, b-microservice-schema, b-features-endpoints, f-messaging-panel, f-use-messaging, f-messaging-types, f-channel-messages, f-features-registry

---

## Structure des 3 fichiers par sous-contexte

### archi.md

- Titre + Scope (2 phrases precises)
- Tableau fichiers avec **lignes** : `| Fichier | Lignes | Role |` (ex: `{service}_api.py:L47-123`)
- API consommee/exposee : `| Method | Endpoint | Description |`
- Schema PG si applicable : `CREATE TABLE` avec constraints (CHECK, UNIQUE, FK)
- Pattern technique : bloc de code montrant le pattern exact (pas pseudo-code)
- Attention : warnings specifiques au contexte

### memory.md

```markdown
## Etat : initial

## Historique
```
Etats valides : `initial` → `en-cours` → `stable` | `fixed` | `regression`

### methodology.md

- "Avant de coder" (3-4 etapes : lire fichiers X, comprendre pattern Y, verifier colonnes en DB)
- "Points d'attention" (pieges specifiques au contexte, pas generiques — inclure JSONB codec, owner/owner_id si applicable)
- "Checklist pre-commit" (colonnes DB, JSONB params, auth, membership, sender, wc -l, git commit)
- "Tests" (commande exacte avec `cd` + `grep` filter)
