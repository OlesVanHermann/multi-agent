# Multi-Agent System v2.4

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
2. Le web dashboard (http://localhost:8000)
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
├── project-config.md            # Configuration (créé par 000)
│
├── prompts/                     # Prompts des agents
│   ├── CONVENTIONS.md           # Conventions de numérotation
│   ├── PATHS.md                 # Variables de chemins
│   ├── 000-architect.md         # Architect (point d'entrée)
│   ├── 0XX-*.md                 # Super-Masters (001-099)
│   ├── 100-*.md                 # Masters
│   ├── 200-*.md                 # Explorers
│   ├── 3XX-*.md                 # Developers (créés par 000)
│   ├── 400-*.md                 # Integrators
│   ├── 5XX-*.md                 # Testers
│   └── 600-*.md                 # Releasers
│
├── examples/                    # Exemples MCP OnlyOffice
│   ├── prompts/                 # Prompts dev spécialisés
│   ├── knowledge/               # INVENTORY exemples
│   └── pool-requests/           # PR exemples
│
├── templates/                   # Templates vides
│   ├── prompts/
│   ├── knowledge/
│   └── pool-requests/
│
├── scripts/                     # Scripts d'orchestration
│   ├── infra.sh                 # start/stop infrastructure + Agent 000
│   ├── agent.sh                 # start/stop agents workers
│   ├── send.sh                  # Envoyer message
│   ├── watch.sh                 # Voir logs
│   └── monitor.py               # Monitoring
│
├── web/                         # Web dashboard
│   ├── backend/                 # FastAPI + Uvicorn (port 8000)
│   ├── frontend/                # React + Vite
│   ├── keycloak/                # Auth config (optionnel)
│   ├── nginx/                   # Reverse proxy config
│   ├── docker-compose.yml       # Docker production
│   └── start.sh                 # Quick start script
│
├── core/
│   ├── agent-bridge/            # Bridge PTY + Redis Streams
│   └── bridge/                  # SSH tunnel Mac↔VM
│
├── docs/                        # Documentation
│   └── BRIDGE.md                # Doc technique du bridge
│
├── infrastructure/              # Docker, setup
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
├── sessions/                    # Sessions agents
├── logs/                        # Logs
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
| `FRAMEWORK-SCRIPTS.md` | **OBLIGATOIRE - Liste des scripts à utiliser** |
| `pool-requests/knowledge/*.md` | Inventaires (tracking ❌/✅) |
| `examples/` | Exemples à suivre |

---

## Instructions Claude

### Règle critique

**Si tu lis un fichier `prompts/XXX-*.md`, tu DEVIENS cet agent et tu EXÉCUTES IMMÉDIATEMENT sa section DÉMARRAGE.**

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

Les agents DOIVENT consulter [`FRAMEWORK-SCRIPTS.md`](FRAMEWORK-SCRIPTS.md) pour la liste complète.

```bash
# ❌ MAUVAIS - Créer un script personnalisé
python3 << 'EOF'
import json
data = {"key": "value"}
print(json.dumps(data))
EOF

# ✅ BON - Utiliser un script du framework
python3 $BASE/framework/generate_structure.py --input data.json
```

**SI aucun script n'existe :** ARRÊTER et SIGNALER à Agent 000 (Architect)

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
python -m pytest tests/ --cov=core --cov-report=term-missing
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
curl -o core/agent-bridge/agent.py \
  https://raw.githubusercontent.com/USER/multi-agent/main/core/agent-bridge/agent.py

# Redémarrer
./scripts/infra.sh stop
./scripts/agent.sh start all
```

---

*Multi-Agent System v2.4 - Février 2026*
