# Multi-Agent System v2.11

Système d'orchestration multi-agents pour projets de développement complexes avec Claude Code.

---

## Vue d'ensemble

Ce système permet de faire tourner jusqu'à **1000 agents** en parallèle avec :

- **Pipeline structurée** : agents spécialisés avec rôles définis
- **Isolation Git** : chaque dev travaille dans son propre clone/branche
- **Communication Redis Streams** : coordination temps réel avec historique
- **Sessions Claude** : prompt caching pour ~90% d'économie de tokens
- **Hiérarchie claire** : Architect (000) → Super-Master → Master → Workers
- **Web dashboard** : monitoring temps réel (port 8050)
- **Auth Keycloak** : JWT sur toutes les routes API

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    HIÉRARCHIE DES AGENTS                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  000 ARCHITECT ──────────────────────────────────────────────── │
│  │ Point d'entrée, configure le système, modifie les prompts    │
│  │ Démarrage: ./scripts/infra.sh start                          │
│  └────────────────────────────────────────────────────────────  │
│                              │                                   │
│                              ▼                                   │
│  0XX SUPER-MASTERS (001-099) ────────────────────────────────── │
│  │ Coordination multi-projets, vision globale                   │
│  └────────────────────────────────────────────────────────────  │
│                              │                                   │
│                              ▼                                   │
│  1XX MASTERS ────────────────────────────────────────────────── │
│  │ Coordination d'un projet, dispatch aux workers               │
│  └────────────────────────────────────────────────────────────  │
│                              │                                   │
│         ┌────────────────────┼────────────────────┐             │
│         ▼                    ▼                    ▼             │
│  2XX EXPLORERS      3XX DEVELOPERS       4XX INTEGRATORS        │
│  │ Analyse          │ Code               │ Merge Git            │
│  │ Création SPEC    │ Implémentation     │ Synchronisation      │
│  └──────────────────┴────────────────────┴────────────────────  │
│                              │                                   │
│                              ▼                                   │
│  5XX TESTERS ────────────────────────────────────────────────── │
│  │ Tests unitaires, intégration, QA                             │
│  └────────────────────────────────────────────────────────────  │
│                              │                                   │
│                              ▼                                   │
│  6XX RELEASERS ──────────────────────────────────────────────── │
│  │ Release, déploiement, publication                            │
│  └────────────────────────────────────────────────────────────  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Installer

```bash
git clone https://github.com/OlesVanHermann/multi-agent.git ~/multi-agent
cd ~/multi-agent
pip install -r requirements.txt
```

Voir `setup/HOW_TO_SETUP.md` pour l'installation complète (Redis, Keycloak, profils Claude).

### 2. Configurer les secrets

```bash
cp setup/secrets.cfg.template setup/secrets.cfg
$EDITOR setup/secrets.cfg    # REDIS_PASSWORD, KEYCLOAK_ADMIN_PASSWORD, etc.
```

**Note :** `setup/secrets.cfg` n'est jamais dans le repo GitHub. Seul `secrets.cfg.template` est versionné.

### 3. Lancer tout (infrastructure + agents)

```bash
./scripts/agent.sh start all
```

Ce script démarre automatiquement :
1. Docker, Redis, Keycloak (via `infra.sh`)
2. Le web dashboard (http://localhost:8050)
3. L'agent 000 (Architect) avec Claude + bridge
4. Tous les agents définis dans `prompts/`

Pour lancer uniquement l'infrastructure + Architect :

```bash
./scripts/infra.sh start
```

---

## Structure

```
multi-agent/
├── CLAUDE.md                    # CE FICHIER
├── README.md                    # Vitrine GitHub
├── requirements.txt             # Dépendances Python
│
├── prompts/                     # Prompts des agents
│   ├── CONVENTIONS.md           # Conventions de numérotation
│   ├── PATHS.md                 # Variables de chemins
│   ├── RULES.md                 # Règles communes
│   ├── AGENT.md                 # Loader x45 (symlinké)
│   ├── CHROME.md                # Règles CDP/Chrome
│   ├── 000-hub-master/          # Architect (hub)
│   ├── 010-mono-exemple/        # Exemple pipeline mono
│   ├── 011-x45-exemple/         # Exemple pipeline x45
│   ├── 012-z21-exemple/         # Exemple pipeline z21
│   ├── 150-create-mono/         # Créateur d'agents mono
│   ├── 160-create-x45/          # Créateur de pipelines x45
│   ├── 170-create-z21/          # Créateur de pipelines z21
│   ├── *.login                  # Profils Claude (8 templates)
│   └── *.model                  # Modèles (haiku/sonnet/opus)
│
├── examples/                    # Exemples complets par mode
│   ├── 1-mono-simple/           # Pipeline mono minimal
│   ├── 2-mono-complet/          # Pipeline mono complet
│   ├── 3-x45-simple/            # Pipeline x45 minimal
│   ├── 4-x45-complet/           # Pipeline x45 complet
│   └── 5-z21-simple/            # Pipeline z21 minimal
│
├── templates/                   # Templates réutilisables
│   ├── prompts/                 # Template developer 3XX
│   ├── knowledge/               # Template INVENTORY
│   ├── pool-requests/           # Templates PR-DOC/SPEC/TEST
│   ├── project-config.md.template
│   └── x45/                    # Structure projet x45 vide
│
├── framework/                   # Outils Chrome/CDP
│   ├── cdp-bridge/              # Extension Chrome (remplace port 9222)
│   ├── chrome-cdp/              # Client Python CDP
│   ├── chrome-bridge.py         # Bridge WebSocket
│   ├── chrome.sh                # Lancement Chrome headless
│   ├── crawl2.py / crawl3.py    # Crawleurs
│   └── cdp-extract.py / cdp-read.py
│
├── scripts/                     # Scripts d'orchestration
│   ├── agent-bridge/            # Bridge Python (agent.py, orchestrator.py)
│   ├── infra.sh                 # start/stop infrastructure + Agent 000
│   ├── agent.sh                 # start/stop agents workers
│   ├── send.sh                  # Envoyer message Redis
│   ├── watch.sh                 # Voir logs agents
│   ├── status.sh                # Statut infrastructure
│   ├── proxy.sh                 # Reverse proxy :80 → :8050
│   └── web.sh                   # start/stop dashboard web
│
├── patch/                       # Hub pipeline tools (opérateur)
│   ├── upgrade.sh               # Mise à jour framework depuis GitHub
│   ├── sync-to-git.sh           # Sync projet → git
│   ├── hub-receive.sh           # Lister patches en attente
│   ├── hub-cherry-pick.sh       # Cherry-pick un patch
│   ├── hub-release.sh           # Tag + push GitHub
│   ├── HOW_TO_PATCH.md          # Guide workflow patches
│   ├── HOW_TO_UPGRADE.md        # Guide mise à jour
│   ├── SETUP-HUB.md             # Setup machine hub
│   └── SETUP-CLIENT.md          # Setup machine client
│
├── setup/                       # Installation et configuration
│   ├── secrets.cfg.template      # Template secrets (copier → secrets.cfg)
│   ├── HOW_TO_SETUP.md          # Guide d'installation complet
│   ├── install_keycloak.sh      # Installer Keycloak
│   ├── install_redis.sh         # Installer Redis
│   ├── login_create.sh          # Créer profil login Claude
│   ├── keycloak_user_create.sh  # Créer user Keycloak
│   ├── keycloak_user_delete.sh  # Supprimer user Keycloak
│   ├── keycloak_user_list.sh    # Lister users Keycloak
│   └── keycloak_passwd_modify.sh # Changer mot de passe
│
├── web/                         # Web dashboard
│   ├── backend/                 # FastAPI + Uvicorn (port 8050)
│   ├── frontend/                # React + Vite
│   ├── keycloak/                # Auth config
│   ├── nginx/                   # Reverse proxy config
│   ├── start.sh                 # Quick start (dev/prod)
│   └── docker-compose.yml       # Docker production
│
├── docs/                        # Documentation
│   ├── BRIDGE.md                # Doc technique du bridge
│   ├── AUTH.md                  # Guide authentification
│   ├── FRONTEND.md              # Guide dashboard
│   ├── AGENT_MONO.md            # Format agent mono
│   └── AGENT_X45-*.md           # Docs x45 (architecture, conventions, etc.)
│
├── tests/                       # Tests unitaires framework
│
├── pool-requests/               # Queue de travail (projet)
│   ├── pending/                 # À traiter
│   ├── assigned/                # En cours
│   ├── done/                    # Terminés
│   ├── specs/                   # Spécifications
│   ├── tests/                   # Manifests tests
│   ├── knowledge/               # Inventaires
│   └── state/                   # État
│
├── login/                       # Profils Claude Code (API credentials)
│   └── claude1a/ … claude4b/   # 8 profils (à configurer)
│
├── sessions/                    # Sessions agents (projet)
├── logs/                        # Logs (projet)
├── removed/                     # Archive safe-delete
└── project/                     # VOTRE PROJET ICI
```

---

## Convention de numérotation

| Plage | Type | Modifie prompts |
|-------|------|-----------------|
| **000** | **Architect** | **OUI** |
| 001-099 | Super-Masters | Non |
| 100-199 | Masters | Non |
| 200-299 | Explorers | Non |
| 300-399 | Developers | Non |
| 400-499 | Integrators | Non |
| 500-599 | Testers | Non |
| 600-699 | Releasers | Non |
| 700-799 | Documenters | Non |
| 800-899 | Monitors | Non |
| 900-999 | Réservé | Non |

**Règle fondamentale :** Seul l'agent 000 (Architect) peut modifier les prompts.

---

## Pipeline

```
000 Architect (configure + supervise)
         │
         ▼
200 Explorer (analyse) → crée SPEC
         │
         ▼
100 Master (dispatch)
         │
    ┌────┼────┬────┐
    ▼    ▼    ▼    ▼
  300  301  302  303  (Developers - parallèle)
    │    │    │    │
    └────┴────┴────┘
         │
         ▼
400 Merge (cherry-pick)
         │
         ▼
500 Test (validation)
         │
         ▼
600 Release (publication)
```

---

## Communication

### Redis Streams (agent.py bridge)

```bash
# Envoyer un message à un agent
./scripts/send.sh 300 "Analyse le README"

# Ou directement via Redis
redis-cli XADD "ma:agent:300:inbox" '*' prompt "message" from_agent "cli" timestamp "$(date +%s)"
```

### Legacy (Redis Lists)

```bash
redis-cli RPUSH "ma:inject:300" "go"
```

Voir `docs/BRIDGE.md` pour la documentation complète du bridge.

### Pool Requests (Git)

```
pending/  →  assigned/  →  done/
   │            │            │
 créé        traité      terminé
```

---

## Commandes

```bash
# ── Infrastructure ──
./scripts/infra.sh start          # Docker, Redis, Keycloak, Dashboard, Agent 000
./scripts/infra.sh stop           # Tout arrêter

# ── Agents ──
./scripts/agent.sh start all     # Lancer tous les agents
./scripts/agent.sh start 300     # Lancer un agent spécifique
./scripts/agent.sh stop all      # Arrêter les agents (sauf 000)
./scripts/agent.sh stop 300      # Arrêter un agent

# ── Communication ──
./scripts/send.sh 300 "message"  # Envoyer un message
./scripts/watch.sh 300           # Voir les réponses en temps réel

# ── Dashboard web ──
./scripts/web.sh start           # Build frontend + uvicorn :8050
./scripts/web.sh stop            # Arrêter
./scripts/web.sh rebuild         # Force rebuild frontend

# ── Proxy ──
./scripts/proxy.sh start         # Reverse proxy 0.0.0.0:80 → 127.0.0.1:8050
./scripts/proxy.sh stop

# ── Monitoring ──
python3 scripts/agent-bridge/healthcheck.py

# ── Hub (framework dev) ──
./patch/hub-receive.sh                     # Lister les patches
./patch/hub-cherry-pick.sh <branch>        # Cherry-pick un patch
./patch/hub-release.sh [patch|minor|major] # Tag + push GitHub
```

---

## Fichiers clés

| Fichier | Rôle |
|---------|------|
| `prompts/000-hub-master/` | Architect — point d'entrée, configure tout |
| `prompts/PATHS.md` | Variables de chemins |
| `setup/secrets.cfg` | Secrets (Redis, Keycloak, etc.) |
| `project-config.md` | Configuration du projet (créé par 000) |
| `pool-requests/knowledge/*.md` | Inventaires (tracking) |
| `examples/` | Exemples à suivre |

---

## x45 Mode

Mode alternatif de pipeline auto-améliorante. Chaque agent = 3 fichiers (`system.md` + `memory.md` + `methodology.md`) avec boucles de feedback automatiques.

### Détection du mode

Le mode est déterminé automatiquement par le format des prompts présents :

- **Pipeline standard** : `prompts/XXX-nom/XXX-nom.md` (fichier unique)
- **x45** : `prompts/XXX-nom/XXX-system.md` + `XXX-memory.md` + `XXX-methodology.md`

### Quick start x45

```bash
# Copier templates/x45/ → prompts/ et templates/x45/project/ → project/
$EDITOR prompts/900/memory.md            # Orientation projet
./scripts/infra.sh start                 # Redis + Dashboard + Agent 900
./scripts/send.sh 900 "go"              # 900 → 945/system.md
./scripts/agent.sh start 945
./scripts/send.sh 945 "go"              # 945 → tous les system.md
./scripts/agent.sh start all            # Démarre tous les agents
./scripts/send.sh 200 "go"              # Lance le pipeline
```

### Scripts créateurs

| Script | Rôle |
|--------|------|
| `prompts/150-create-mono/` | Créer un agent mono |
| `prompts/160-create-x45/` | Créer un pipeline x45 |
| `prompts/170-create-z21/` | Créer un pipeline z21 |

Voir `examples/` et `docs/AGENT_X45-*.md`.

---

## Mise à jour

### Via upgrade.sh (machines projet)

```bash
./patch/upgrade.sh --dry-run    # Voir ce qui va changer
./patch/upgrade.sh              # Appliquer
```

Le script met à jour les répertoires framework (`scripts/`, `web/`, `docs/`, `patch/`, `setup/`, `templates/`, `examples/`, `framework/`, `tests/`) et préserve les données projet (`prompts/`, `pool-requests/`, `project/`, `sessions/`, `logs/`).

`setup/secrets.cfg` n'est jamais écrasé.

### Via git pull (machines avec accès GitHub)

```bash
./scripts/infra.sh stop
git pull origin main
./scripts/agent.sh start all
```

Voir `patch/HOW_TO_UPGRADE.md` pour le guide complet.

---

## Instructions Claude

### Règle critique

**Si tu lis un fichier `prompts/XXX-*.md`, tu DEVIENS cet agent et tu EXÉCUTES IMMÉDIATEMENT sa section DÉMARRAGE.**

**Si tu lis un répertoire `prompts/XXX/` (mode x45), lis AGENT.md + system.md + memory.md + methodology.md dans cet ordre, puis EXÉCUTE.**

- NE JAMAIS demander "Que veux-tu faire ?"
- NE JAMAIS résumer le contenu du prompt
- EXÉCUTER directement les instructions

### Workflow

1. Lire `CLAUDE.md` (ce fichier) pour le contexte
2. Si prompt agent lu → DEVENIR l'agent
3. Exécuter sans confirmation supplémentaire

---

## RÈGLE ABSOLUE

**STRICTEMENT OBÉIR AUX PROMPTS.**

- NE JAMAIS improviser ou décider par toi-même
- NE JAMAIS utiliser d'autres scripts que ceux décrits dans ce prompt
- NE JAMAIS contourner le workflow défini
- Si quelque chose ne fonctionne pas → SIGNALER, ne pas inventer de solution
- L'utilisateur décide, pas toi

**INTERDIT:** arrêter Chrome, fermer le dernier tab, utiliser MCP chrome-devtools, utiliser Playwright

**Méthode:** CDP direct via websockets (port 9222)

---

## Règles de sécurité

### JAMAIS de suppression définitive

**INTERDIT :** `rm -rf`, `rm -r`, `rm`, `rmdir`, `unlink`

**OBLIGATOIRE :** Utiliser `safe_rm` ou déplacer vers `$BASE/removed/`

```bash
# MAUVAIS - INTERDIT
rm -rf /chemin/vers/dossier

# BON - Déplacer vers removed/
mv /chemin/vers/dossier $BASE/removed/$(date +%Y%m%d_%H%M%S)_dossier

# OU utiliser la fonction safe_rm
safe_rm /chemin/vers/dossier
```

### Fonction safe_rm

```bash
safe_rm() {
    local target="$1"
    local removed_dir="$HOME/multi-agent/removed"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local name=$(basename "$target")
    mkdir -p "$removed_dir"
    mv "$target" "$removed_dir/${timestamp}_${name}"
    echo "Moved to: $removed_dir/${timestamp}_${name}"
}
```

### JAMAIS créer des scripts personnalisés

**INTERDIT :** `python3 << 'EOF'`, `bash << 'EOF'`, créer des scripts ad-hoc

**OBLIGATOIRE :** Utiliser UNIQUEMENT les scripts dans `$BASE/scripts/` et `$BASE/framework/`.

---

## Développement du framework

### Workflow patches (multi-machines)

```
Machine projet  →  push patch/  →  Hub (bare repo)  →  cherry-pick  →  GitHub
```

Voir `patch/HOW_TO_PATCH.md` pour le workflow complet.

### Tests

```bash
python -m pytest tests/ -v
python -m pytest tests/ --cov=scripts --cov-report=term-missing
```

### Release

```bash
./patch/hub-release.sh patch    # Incrémente, tag, push GitHub
```

Ou manuellement :

```bash
git add -A && git commit -m "release: v2.5.X - Description"
git tag -a v2.5.X -m "v2.5.X - Description"
git push origin main --tags
```

---

*Multi-Agent System v2.11 - Mars 2026*
