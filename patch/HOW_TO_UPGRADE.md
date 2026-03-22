# Guide de Mise à Jour

Ce guide explique comment mettre à jour votre déploiement multi-agent vers une nouvelle version.

---

## Guides par version

Le script de mise à jour est dans `patch/upgrade.sh`. Il préserve automatiquement les fichiers projet et met à jour uniquement le framework.

---

## Structure des fichiers

### Fichiers FRAMEWORK (mis à jour automatiquement)

Ces fichiers viennent du repo officiel et ne doivent **pas** être modifiés localement :

```
scripts/agent-bridge/     # Bridge Python du framework

scripts/                  # Scripts d'orchestration
├── *.sh
└── *.py

patch/                    # Scripts de patch/upgrade
├── upgrade.sh
├── hub-release.sh
└── ...

docs/                     # Documentation framework
requirements.txt          # Dépendances Python
UPGRADE.md               # Ce fichier
```

### Fichiers PROJET (à conserver lors des mises à jour)

Ces fichiers sont spécifiques à votre projet :

```
prompts/                  # Vos prompts personnalisés
pool-requests/           # Données runtime
├── knowledge/           # Vos inventaires
project/                 # Votre code source
project-config.md        # Votre configuration
logs/                    # Logs (peuvent être supprimés)
sessions/                # Sessions (peuvent être supprimés)
```

---

## Processus de mise à jour

### Étape 1: Identifier votre version actuelle

```bash
git describe --tags 2>/dev/null || git log --oneline -1
```

### Étape 2: Sauvegarder vos fichiers projet

```bash
BACKUP_DIR="../multi-agent-backup-$(date +%Y%m%d)"
mkdir -p $BACKUP_DIR
cp -r prompts/ $BACKUP_DIR/
cp -r pool-requests/knowledge/ $BACKUP_DIR/
cp project-config.md $BACKUP_DIR/ 2>/dev/null || true
echo "Backup: $BACKUP_DIR"
```

### Étape 3: Arrêter les agents

```bash
./scripts/infra.sh stop 2>/dev/null || true
tmux kill-server 2>/dev/null || true
```

### Étape 4: Lancer le script de mise à jour

```bash
# Simuler d'abord (aucune modification)
./patch/upgrade.sh --dry-run

# Appliquer la mise à jour
./patch/upgrade.sh
```

### Étape 6: Installer les dépendances

```bash
pip install -r requirements.txt
```

### Étape 7: Vérifier et redémarrer

```bash
python3 scripts/agent-bridge/healthcheck.py
./scripts/agent.sh start all
```

---

## Script de mise à jour automatique

```bash
#!/bin/bash
# upgrade.sh

set -e
REPO_URL="https://github.com/YOUR-ORG/multi-agent.git"
BRANCH="${1:-main}"

echo "=== Multi-Agent Upgrade ==="

# Backup
BACKUP_DIR="../multi-agent-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p $BACKUP_DIR
cp -r prompts/ $BACKUP_DIR/
cp -r pool-requests/knowledge/ $BACKUP_DIR/ 2>/dev/null || true
cp project-config.md $BACKUP_DIR/ 2>/dev/null || true
echo "Backup: $BACKUP_DIR"

# Stop agents
./scripts/infra.sh stop 2>/dev/null || true

# Download & update framework only
TEMP_DIR=$(mktemp -d)
git clone --depth 1 --branch $BRANCH $REPO_URL $TEMP_DIR

rsync -av --delete $TEMP_DIR/scripts/ ./scripts/
rsync -av --delete $TEMP_DIR/patch/ ./patch/
rsync -av --delete $TEMP_DIR/docs/ ./docs/
cp $TEMP_DIR/requirements.txt ./
cp $TEMP_DIR/CLAUDE.md ./
cp $TEMP_DIR/UPGRADE.md ./
cp $TEMP_DIR/README.md ./

mkdir -p ./removed && mv $TEMP_DIR ./removed/temp-upgrade-$(date +%s)

# Install deps
pip install -r requirements.txt

echo ""
echo "=== Mise à jour terminée ==="
echo "Consultez patch/ pour les scripts de gestion des patches"
```

---

## Historique des versions

| Version | Date | Changements majeurs |
|---------|------|---------------------|
| v2.4 | 2026-02 | Format mono/x45/z21, Chrome Bridge extension, agent 150, patch/ dir |
| v2.3 | 2026-02 | Dashboard web React+FastAPI, Keycloak auth, proxy.sh |
| v2.2 | 2026-01 | x45 auto-amélioration, satellites, crontab-scheduler |
| v2.1 | 2026-01 | Bridge Redis Streams, healthcheck, tmux batching |
| v2.0 | 2026-01 | Version initiale |

---

*Issues: https://github.com/YOUR-ORG/multi-agent/issues*
