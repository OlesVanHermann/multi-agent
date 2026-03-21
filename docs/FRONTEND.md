# Multi-Agent Frontend - Spécifications

## Vue d'ensemble

Interface web pour gérer et monitorer les 1000 agents multi-agent sans avoir 1000 terminaux ouverts.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           NGINX                                      │
│                       (reverse proxy)                                │
├─────────────────────────────────────────────────────────────────────┤
│  /                 → Frontend React (static)                         │
│  /api/*            → Backend FastAPI :8090                           │
│  /ws/terminal/*    → Backend → ttyd (WebSocket)                      │
│  /auth/*           → Keycloak :8080                                  │
└─────────────────────────────────────────────────────────────────────┘
                                │
               ┌────────────────┼────────────────┐
               │                │                │
        ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
        │  Keycloak   │  │   FastAPI   │  │    Redis    │
        │    :8080    │  │    :8090    │  │    :6379    │
        │             │  │             │  │             │
        │ - Auth      │  │ - API REST  │  │ - Streams   │
        │ - JWT       │  │ - WebSocket │  │ - Status    │
        │ - Roles     │  │ - ttyd pool │  │             │
        └─────────────┘  └──────┬──────┘  └─────────────┘
                                │
                        ┌───────▼───────┐
                        │  tmux sessions │
                        │  agent-100...  │
                        │  agent-900...  │
                        └───────────────┘
```

---

## Interface utilisateur

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│  MULTI-AGENT DASHBOARD                                         [dev1] [Logout]              │
├───────────────────────┬─────────────────────────────────┬───────────────────────────────────┤
│   AGENTS (1000)       │   CONTROL PLANE (100/900)       │   AGENT SÉLECTIONNÉ              │
│                       │                                 │   [▼ Agent 300 - Developer]      │
│  ┌──┬──┬──┬──┬──┬──┐  │  ┌─────────────────────────┐    │  ┌─────────────────────────────┐ │
│  │00│01│02│03│04│05│  │  │ $ agent-100             │    │  │ $ agent-300                 │ │
│  ├──┼──┼──┼──┼──┼──┤  │  │                         │    │  │                             │ │
│  │  │  │  │  │  │  │  │  │ HEARTBEAT 300 | WORKING │    │  │ Analyzing example.com...    │ │
│  │🟢│🟢│🟢│🟢│🟢│🟢│  │  │ HEARTBEAT 301 | IDLE    │    │  │ Found 479 pages             │ │
│  ├──┼──┼──┼──┼──┼──┤  │  │ HEARTBEAT 302 | WORKING │    │  │ Downloading: 234/479        │ │
│  │  │  │  │  │  │  │  │  │                         │    │  │ ████████████░░░░░░ 49%     │ │
│  │🟢│🟠│🟢│🟢│🟢│🟢│  │  │ FROM:300|DONE example   │    │  │                             │ │
│  └──┴──┴──┴──┴──┴──┘  │  │ SUCCESS - 479 pages     │    │  │                             │ │
│                       │  │                         │    │  │                             │ │
│  0XX Super-Masters 🟢 │  │ Dispatching to 306...   │    │  │                             │ │
│  1XX Masters       🟢 │  │                         │    │  │                             │ │
│  2XX Explorers     🟢 │  │ > send 306 "extract"    │    │  │ > _                         │ │
│  3XX Developers    🟠 │  │                         │    │  │                             │ │
│  4XX Integrators   🟢 │  └─────────────────────────┘    │  └─────────────────────────────┘ │
│  5XX Testers       🟢 │                                 │                                  │
│  6XX Releasers     🟢 │  [Send] [Clear] [Restart]       │  [Send] [Clear] [Restart]        │
│  9XX Architects    🟢 │                                 │                                  │
├───────────────────────┴─────────────────────────────────┴───────────────────────────────────┤
│  STATUS: 8 agents running | 1 active | Redis: ✓ | Last update: 2s ago          [Refresh]   │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3 colonnes

| Colonne | Contenu | Interaction |
|---------|---------|-------------|
| **Gauche** | Grille des agents (carrés colorés) | Clic = sélectionne agent pour colonne droite |
| **Centre** | Terminal Control Plane (100 ou 900) | Input/output direct via ttyd |
| **Droite** | Terminal agent sélectionné (200-800) | Input/output direct via ttyd |

### Légende couleurs

| Couleur | État | Description |
|---------|------|-------------|
| 🟢 Vert | IDLE | Agent en attente, pas de tâche |
| 🟠 Orange | WORKING | Agent en cours d'exécution |
| 🔴 Rouge | BLOCKED/ERROR | Agent bloqué ou en erreur |
| ⚫ Gris | STOPPED | Session tmux arrêtée |

---

## Structure du projet

```
multi-agent/
└── web/
    ├── docker-compose.yml
    ├── nginx/
    │   └── nginx.conf
    ├── keycloak/
    │   └── realm-multi-agent.json
    ├── backend/
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   ├── server.py          # FastAPI principal
    │   ├── auth.py            # Validation JWT Keycloak
    │   └── ttyd_pool.py       # Gestion pool ttyd
    └── frontend/
        ├── package.json
        ├── vite.config.js
        ├── index.html
        └── src/
            ├── main.jsx
            ├── App.jsx
            ├── AuthProvider.jsx
            ├── components/
            │   ├── AgentGrid.jsx
            │   ├── Terminal.jsx
            │   └── StatusBar.jsx
            └── index.css
```

---

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Frontend | React + Vite |
| Terminal web | ttyd + xterm.js |
| Backend | FastAPI (Python) |
| Auth | Keycloak (local) |
| Communication | Redis Streams + WebSocket |
| Reverse proxy | Nginx |
| Conteneurs | Docker Compose |

---

## API Backend

### REST

```
GET  /api/agents              → Liste agents avec statut
GET  /api/agent/{id}          → Détails d'un agent
POST /api/agent/{id}/send     → Envoyer message à un agent
POST /api/agent/{id}/restart  → Redémarrer un agent
```

### WebSocket

```
WS /ws/messages               → Stream temps réel des messages inter-agents
WS /ws/terminal/{agent_id}    → Terminal interactif (proxy ttyd)
```

---

## Authentification

### Keycloak local

```json
{
  "realm": "multi-agent",
  "clients": ["multi-agent-web"],
  "roles": ["admin", "operator", "viewer"],
  "users": [
    { "username": "dev1", "roles": ["admin"] }
  ]
}
```

### Flux

```
Frontend → Keycloak (login) → JWT token
Frontend → Backend (+ JWT) → Validation locale (clé publique)
```

### Rôles

| Rôle | Droits |
|------|--------|
| admin | Tout (view, send, restart, kill) |
| operator | View + send commands |
| viewer | Read only |

---

## Fonctionnalités

### MVP (v1)

- [ ] Grille agents avec statut couleur
- [ ] Terminal Control Plane (100/900)
- [ ] Terminal agent sélectionné
- [ ] Auth Keycloak
- [ ] Refresh automatique statut

### v2 (futures)

- [ ] Timeline messages entre agents (graphe visuel)
- [ ] Boutons kill/restart groupés
- [ ] Filtres par type d'agent
- [ ] Export logs
- [ ] Mode sombre/clair
- [ ] Notifications (agent bloqué, erreur)

---

## Lancement

```bash
# 1. Build frontend
cd web/frontend
npm install
npm run build

# 2. Lancer les services
cd ..
docker-compose up -d

# 3. Accéder
# → http://localhost
# → Login: admin / changeme (changer au premier login)
```

---

## Intégration avec multi-agent existant

Le frontend se branche sur :

1. **Redis** - Déjà utilisé pour la communication inter-agents
2. **tmux** - Sessions `agent-{id}` existantes
3. **Heartbeat** - Données de statut déjà envoyées au Master (100)

Aucune modification du code agent existant requise.

---

*Document créé : Janvier 2026*
