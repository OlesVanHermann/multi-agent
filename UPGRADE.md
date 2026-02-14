# Guide de Mise à Jour

Ce guide explique comment mettre à jour votre déploiement multi-agent vers une nouvelle version.

---

## Guides par version

| De | Vers | Guide |
|----|------|-------|
| v2.0 | v2.1 | [upgrades/2.0-to-2.1.md](upgrades/2.0-to-2.1.md) |

---

## Structure des fichiers

### Fichiers FRAMEWORK (mis à jour automatiquement)

Ces fichiers viennent du repo officiel et ne doivent **pas** être modifiés localement :

```
core/                     # Code Python du framework
├── agent-bridge/
└── agent-runner/

scripts/                  # Scripts d'orchestration
├── bridge/
└── *.sh

docs/                     # Documentation framework
upgrades/                 # Guides de migration
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

### Étape 4: Télécharger et lancer le script de mise à jour

```bash
# Télécharger le script depuis GitHub
curl -O https://raw.githubusercontent.com/OlesVanHermann/multi-agent/main/upgrade.sh
chmod +x upgrade.sh

# Simuler d'abord (aucune modification)
./upgrade.sh --dry-run

# Appliquer la mise à jour
./upgrade.sh
```

Ou avec wget :
```bash
wget https://raw.githubusercontent.com/OlesVanHermann/multi-agent/main/upgrade.sh
chmod +x upgrade.sh
./upgrade.sh
```

### Étape 5: Lire le guide de migration spécifique

Consultez le fichier correspondant dans `upgrades/` pour les actions spécifiques à votre version.

### Étape 6: Installer les dépendances

```bash
pip install -r requirements.txt
```

### Étape 7: Vérifier et redémarrer

```bash
python3 core/agent-bridge/healthcheck.py
./scripts/agent.sh start all
```

---

## Script de mise à jour automatique

```bash
#!/bin/bash
# upgrade.sh

set -e
REPO_URL="https://github.com/OlesVanHermann/multi-agent.git"
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

rsync -av --delete $TEMP_DIR/core/ ./core/
rsync -av --delete $TEMP_DIR/scripts/ ./scripts/
rsync -av --delete $TEMP_DIR/docs/ ./docs/
rsync -av --delete $TEMP_DIR/upgrades/ ./upgrades/
cp $TEMP_DIR/requirements.txt ./
cp $TEMP_DIR/CLAUDE.md ./
cp $TEMP_DIR/UPGRADE.md ./
cp $TEMP_DIR/README.md ./

mkdir -p ./removed && mv $TEMP_DIR ./removed/temp-upgrade-$(date +%s)

# Install deps
pip install -r requirements.txt

echo ""
echo "=== Mise à jour terminée ==="
echo "Consultez upgrades/ pour les actions spécifiques à votre version"
```

---

## Historique des versions

| Version | Date | Changements majeurs |
|---------|------|---------------------|
| v2.1 | 2026-01 | Bridge Redis Streams, CLI tools, healthcheck |
| v2.0 | 2026-01 | Version initiale |

---

*Issues: https://github.com/OlesVanHermann/multi-agent/issues*
