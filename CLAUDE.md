# Multi-Agent System v2.5

Système d'orchestration multi-agents pour projets de développement complexes.

---

## Vue d'ensemble

Ce système permet de faire tourner jusqu'à **1000 agents** en parallèle avec :

- **Pipeline structurée** : agents spécialisés avec rôles définis
- **Isolation Git** : chaque dev travaille dans son propre clone/branche
- **Communication Redis Streams** : coordination temps réel avec historique
- **Sessions Claude** : prompt caching pour ~90% d'économie de tokens
- **Hiérarchie claire** : Architect (000) → Super-Master → Master → Workers

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    HIÉRARCHIE DES AGENTS                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  000 ARCHITECT ──────────────────────────────────────────────── │
│  │ Point d'entrée, configure le système, modifie les prompts    │
│  │ Démarrage: ./scripts/infra.sh start                            │
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

### 1. Déployer sur une nouvelle machine

```bash
# Copier le dossier multi-agent/
scp -r multi-agent/ user@machine:/chemin/

# Se connecter
ssh user@machine
cd /chemin/multi-agent
```

### 2. Lancer tout (infrastructure + agents)

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
├── README.md                    # Guide de déploiement
├── HOW_TO_SETUP.md              # Installation pas à pas
├── UPGRADE.md                   # Guide de mise à jour
├── requirements.txt             # Dépendances Python
├── project-config.md            # Configuration (créé par 000)
│
├── prompts/                     # Prompts des agents
│   ├── CONVENTIONS.md           # Conventions de numérotation
│   ├── PATHS.md                 # Variables de chemins
│   ├── RULES.md                 # Règles communes
│   ├── AGENT.md                 # Loader x45 (symlinké)
│   ├── CHROME.md                # Règles CDP/Chrome
│   ├── 000/, 100/, 200/         # Super-Master/Master/Explorer x45
│   ├── 341/, 342/, 345/         # Developer x45 (templates)
│   ├── 000-super-master.md      # Super-Master mono (flat)
│   ├── 100-master.md            # Master mono (flat)
│   ├── 150-create-mono/         # Créateur d'agents mono
│   ├── 160-create-x45/          # Créateur de pipelines x45
│   ├── 170-create-z21/          # Créateur de pipelines z21
│   ├── 400-merge.md             # Integrator / 500-test.md / 600-release.md
│   ├── 900-architect.md         # Architect (flat)
│   ├── *.login                  # Profils Claude (8 templates vides)
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
│   ├── monitor.py               # Monitoring Redis
│   └── web.sh                   # start/stop dashboard web
│
├── patch/                       # Hub pipeline tools (opérateur)
│   ├── sync-to-git.sh           # Sync projet → git
│   ├── upgrade.sh               # Mise à jour framework
│   └── hub-*.sh / setup-*.md   # Scripts et guides opérateur
│
├── setup/                       # Installation et configuration
│   ├── install_keycloak.sh / install_redis.sh
│   ├── login_create.sh          # Créer profil login
│   └── keycloak_*.sh            # Gestion users Keycloak
│
├── web/                         # Web dashboard
│   ├── backend/                 # FastAPI + Uvicorn (port 8050)
│   ├── frontend/                # React + Vite
│   ├── keycloak/                # Auth config
│   ├── nginx/                   # Reverse proxy config
│   └── docker-compose.yml       # Docker production
│
├── docs/                        # Documentation
│   ├── BRIDGE.md                # Doc technique du bridge
│   ├── KEYCLOAK.md              # Guide Keycloak
│   └── FRONTEND.md              # Guide dashboard
│
├── tests/                       # Tests unitaires framework
│
├── pool-requests/               # Queue de travail
│   ├── pending/                 # À traiter
│   ├── assigned/                # En cours
│   ├── done/                    # Terminés
│   ├── specs/                   # Spécifications
│   ├── tests/                   # Manifests tests
│   ├── knowledge/               # Inventaires
│   └── state/                   # État
│
├── login/                       # Profils Claude Code (API credentials)
│   └── claude1a/ … claude4b/   # 8 profils (vides — à configurer)
│
├── sessions/                    # Sessions agents
├── logs/                        # Logs
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

### Deux modes disponibles

#### Mode Legacy (agent_runner.py)
```bash
# Redis Lists
redis-cli RPUSH "ma:inject:{AGENT_ID}" "message"
redis-cli RPUSH "ma:inject:300" "go"
```

#### Mode Bridge (agent.py) - RECOMMANDÉ
```bash
# Redis Streams (plus robuste)
./scripts/send.sh 300 "Analyse le README"

# Ou directement
redis-cli XADD "ma:agent:300:inbox" '*' prompt "message" from_agent "cli" timestamp "$(date +%s)"
```

Voir `docs/BRIDGE.md` pour la documentation complète du bridge.

### Pool Requests (Git)

```
pending/  →  assigned/  →  done/
   │            │            │
 créé        traité      terminé
```

---

## Fichiers clés

| Fichier | Rôle |
|---------|------|
| `prompts/000-architect.md` | Point d'entrée, configure tout |
| `prompts/PATHS.md` | Variables de chemins |
| `project-config.md` | Configuration du projet |
| `pool-requests/knowledge/*.md` | Inventaires (tracking ❌/✅) |
| `examples/` | Exemples à suivre |

---

## x45 Mode

Mode alternatif de pipeline auto-améliorante. Chaque agent = 3 fichiers (`system.md` + `memory.md` + `methodology.md`) avec boucles de feedback automatiques.

**Doc complète :** `docs/` (voir BRIDGE.md, FRONTEND.md, KEYCLOAK.md)

### Détection du mode

Le mode est déterminé automatiquement par le format des prompts présents :

- **Pipeline standard** : `prompts/XXX-*.md` (fichiers flat)
- **x45** : `prompts/XXX/system.md` (répertoires avec 3 fichiers)

Un projet utilise un mode ou l'autre, jamais les deux.

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

### Scripts x45

| Script | Rôle |
|--------|------|
| `prompts/160-create-x45/` | Créer un pipeline x45 |
| `prompts/170-create-z21/` | Créer un pipeline z21 |
| `prompts/150-create-mono/` | Créer un agent mono |

### Exemple

Voir `examples/3-x45-simple/` et `examples/4-x45-complet/`.

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

Ajouter dans `.bashrc` ou utiliser directement :

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

**OBLIGATOIRE :** Utiliser UNIQUEMENT les scripts dans `$BASE/framework/`

Les agents utilisent les scripts dans `$BASE/scripts/` et les outils dans `$BASE/framework/`.

### Nettoyage du répertoire removed/

Le répertoire `removed/` peut être nettoyé **manuellement** après vérification :

```bash
# Voir ce qui a été supprimé
ls -la $BASE/removed/

# Supprimer les fichiers de plus de 7 jours (après vérification manuelle)
find $BASE/removed/ -mtime +7 -exec rm -rf {} \;
```

---

## Développement du Multi-Agent System

### Workflow de développement

Ce système est amélioré en continu via les feedbacks utilisateur :

1. **Feedback** → L'utilisateur signale un problème ou propose une amélioration
2. **Test local** → Écrire/exécuter un test unitaire pour reproduire le problème
3. **Fix** → Corriger le code
4. **Vérifier** → Le test passe maintenant
5. **Commit** → Commit avec message descriptif
6. **Release** → Tag + push vers GitHub
7. **Déploiement** → Commandes pour mettre à jour les projets en cours

### Tests unitaires locaux

Avant de corriger, **toujours écrire un test** pour reproduire le bug :

```bash
# Lancer tous les tests
python -m pytest tests/ -v

# Lancer un test spécifique
python -m pytest tests/test_agent_bridge.py -v

# Test avec couverture
python -m pytest tests/ --cov=scripts --cov-report=term-missing
```

Structure des tests :
```
tests/
├── __init__.py
├── test_agent_bridge.py      # Tests du bridge tmux
├── test_redis_comm.py        # Tests communication Redis
├── test_heartbeat.py         # Tests heartbeat
└── fixtures/                 # Données de test
```

### Préparer une release GitHub

```bash
# 1. Vérifier que tout est propre
git status
python -m pytest tests/ -v

# 2. Mettre à jour la version dans CLAUDE.md
# v2.X → v2.Y

# 3. Commit final
git add -A
git commit -m "release: v2.X - Description"

# 4. Tag
git tag -a v2.X -m "Version 2.X - Description"

# 5. Push
git push origin main --tags
```

### Mettre à jour un projet en cours

Pour les projets qui utilisent multi-agent et qui tournent déjà :

```bash
# === SUR LA MACHINE DU PROJET ===

# 1. Tout arrêter
./scripts/infra.sh stop

# 2. Pull les dernières modifications
cd /chemin/vers/multi-agent
git pull origin main

# 3. Tout relancer
./scripts/agent.sh start all

# 4. Vérifier
tmux ls | grep agent
python3 scripts/monitor.py
```

**Mise à jour d'un fichier spécifique sans git pull :**
```bash
# Télécharger directement depuis GitHub
curl -o scripts/agent-bridge/agent.py \
  https://raw.githubusercontent.com/USER/multi-agent/main/scripts/agent-bridge/agent.py

# Redémarrer
./scripts/infra.sh stop
./scripts/agent.sh start all
```

---

*Multi-Agent System v2.5 - Mars 2026*
