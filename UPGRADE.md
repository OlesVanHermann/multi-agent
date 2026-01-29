# Guide de Mise à Jour

Ce guide explique comment mettre à jour votre déploiement multi-agent vers une nouvelle version.

---

## Structure des fichiers

### Fichiers FRAMEWORK (mis à jour automatiquement)

Ces fichiers viennent du repo officiel et ne doivent **pas** être modifiés localement :

```
core/                     # Code Python du framework
├── agent-bridge/
│   ├── agent.py
│   ├── orchestrator.py
│   └── healthcheck.py
└── agent-runner/

scripts/                  # Scripts d'orchestration
├── bridge/
│   ├── start-bridge-agents.sh
│   ├── stop-bridge-agents.sh
│   ├── send.sh
│   ├── watch.sh
│   └── monitor.sh
└── *.sh

docs/                     # Documentation framework
requirements.txt          # Dépendances Python
```

### Fichiers PROJET (à conserver lors des mises à jour)

Ces fichiers sont spécifiques à votre projet :

```
prompts/                  # Vos prompts personnalisés
├── 3XX-*.md             # Prompts dev adaptés à votre projet
└── ...

pool-requests/           # Données runtime
├── knowledge/           # Vos inventaires
├── pending/
├── done/
└── ...

project/                 # Votre code source
project-config.md        # Votre configuration
logs/                    # Logs (peuvent être supprimés)
sessions/                # Sessions (peuvent être supprimés)
```

---

## Processus de mise à jour

### Étape 1: Sauvegarder vos fichiers projet

```bash
cd /chemin/vers/multi-agent

# Créer une sauvegarde
BACKUP_DIR="../multi-agent-backup-$(date +%Y%m%d)"
mkdir -p $BACKUP_DIR

# Sauvegarder les fichiers projet
cp -r prompts/ $BACKUP_DIR/
cp -r pool-requests/knowledge/ $BACKUP_DIR/
cp project-config.md $BACKUP_DIR/ 2>/dev/null || true
cp -r project/ $BACKUP_DIR/ 2>/dev/null || true

echo "Backup créé dans $BACKUP_DIR"
```

### Étape 2: Arrêter les agents

```bash
./scripts/bridge/stop-bridge-agents.sh
# ou
tmux kill-server
```

### Étape 3: Télécharger la nouvelle version

**Option A: Via Git (si vous avez cloné le repo)**

```bash
# Voir votre version actuelle
git describe --tags 2>/dev/null || git log --oneline -1

# Récupérer les mises à jour
git fetch origin
git stash                    # Sauvegarder vos modifications locales
git pull origin main
git stash pop               # Restaurer vos modifications
```

**Option B: Via téléchargement manuel**

```bash
# Télécharger la nouvelle version
cd /tmp
git clone --depth 1 https://github.com/OlesVanHermann/multi-agent.git multi-agent-new
cd -

# Mettre à jour les fichiers framework uniquement
rsync -av --delete /tmp/multi-agent-new/core/ ./core/
rsync -av --delete /tmp/multi-agent-new/scripts/ ./scripts/
rsync -av --delete /tmp/multi-agent-new/docs/ ./docs/
cp /tmp/multi-agent-new/requirements.txt ./
cp /tmp/multi-agent-new/CLAUDE.md ./
cp /tmp/multi-agent-new/UPGRADE.md ./

# Nettoyer
rm -rf /tmp/multi-agent-new
```

### Étape 4: Installer les nouvelles dépendances

```bash
pip install -r requirements.txt
```

### Étape 5: Vérifier la configuration

```bash
# Tester que tout fonctionne
python3 -c "import redis; print('Redis OK')"
python3 core/agent-bridge/healthcheck.py
```

### Étape 6: Redémarrer les agents

```bash
./scripts/bridge/start-bridge-agents.sh all
```

---

## Migrations spécifiques par version

### v2.0 → v2.1

**Nouveaux fichiers ajoutés :**
```
core/agent-bridge/           # NOUVEAU - Bridge Redis Streams
├── agent.py
├── orchestrator.py
├── healthcheck.py
└── __init__.py

scripts/bridge/              # NOUVEAU - Scripts CLI
├── start-bridge-agents.sh
├── stop-bridge-agents.sh
├── send.sh
├── watch.sh
├── monitor.sh
├── inbox.sh
└── outbox.sh

docs/BRIDGE.md               # NOUVEAU - Documentation bridge
```

**Fichiers modifiés :**
```
requirements.txt             # Ajout: pexpect>=4.8.0
README.md                    # Mise à jour documentation
CLAUDE.md                    # Mise à jour documentation
prompts/CONVENTIONS.md       # Simplification mapping profiles
prompts/600-release.md       # Chemins génériques
prompts/900-architect.md     # Chemins génériques
```

**Actions requises :**

1. Installer pexpect :
   ```bash
   pip install pexpect>=4.8.0
   ```

2. Configurer l'environnement Claude (si profil personnalisé) :
   ```bash
   export CLAUDE_CONFIG_DIR=~/.claude
   # ou votre chemin personnalisé
   ```

3. Vérifier Redis :
   ```bash
   redis-cli ping
   ```

4. Adapter vos prompts si nécessaire :
   - Les anciens scripts `scripts/start-agents.sh` fonctionnent toujours
   - Les nouveaux scripts `scripts/bridge/*` utilisent Redis Streams
   - Vous pouvez utiliser l'un ou l'autre

---

## Script de mise à jour automatique

Créez ce script pour automatiser les futures mises à jour :

```bash
#!/bin/bash
# upgrade.sh - Met à jour le framework multi-agent

set -e

REPO_URL="https://github.com/OlesVanHermann/multi-agent.git"
BRANCH="${1:-main}"

echo "=== Multi-Agent Upgrade ==="
echo "Branche: $BRANCH"
echo ""

# 1. Backup
BACKUP_DIR="../multi-agent-backup-$(date +%Y%m%d-%H%M%S)"
echo "[1/5] Backup vers $BACKUP_DIR..."
mkdir -p $BACKUP_DIR
cp -r prompts/ $BACKUP_DIR/
cp -r pool-requests/knowledge/ $BACKUP_DIR/ 2>/dev/null || true
cp project-config.md $BACKUP_DIR/ 2>/dev/null || true

# 2. Stop agents
echo "[2/5] Arrêt des agents..."
./scripts/bridge/stop-bridge-agents.sh 2>/dev/null || true

# 3. Download new version
echo "[3/5] Téléchargement nouvelle version..."
TEMP_DIR=$(mktemp -d)
git clone --depth 1 --branch $BRANCH $REPO_URL $TEMP_DIR

# 4. Update framework files only
echo "[4/5] Mise à jour des fichiers framework..."
rsync -av --delete $TEMP_DIR/core/ ./core/
rsync -av --delete $TEMP_DIR/scripts/ ./scripts/
rsync -av --delete $TEMP_DIR/docs/ ./docs/
cp $TEMP_DIR/requirements.txt ./
cp $TEMP_DIR/CLAUDE.md ./
cp $TEMP_DIR/UPGRADE.md ./
cp $TEMP_DIR/README.md ./

# 5. Install dependencies
echo "[5/5] Installation dépendances..."
pip install -r requirements.txt

# Cleanup
rm -rf $TEMP_DIR

echo ""
echo "=== Mise à jour terminée ==="
echo "Backup: $BACKUP_DIR"
echo ""
echo "Prochaines étapes:"
echo "  1. Vérifier vos prompts dans prompts/"
echo "  2. Lancer: ./scripts/bridge/start-bridge-agents.sh all"
```

Rendez-le exécutable :
```bash
chmod +x upgrade.sh
```

---

## Résolution de problèmes

### Conflit de fichiers

Si vous avez modifié des fichiers framework :

```bash
# Voir les différences
git diff HEAD origin/main -- core/ scripts/

# Garder vos modifications dans un patch
git diff core/ scripts/ > my-changes.patch

# Mettre à jour puis réappliquer
git checkout origin/main -- core/ scripts/
git apply my-changes.patch
```

### Prompts incompatibles

Si vos prompts utilisent d'anciennes conventions :

1. Comparer avec les nouveaux templates dans `prompts/`
2. Vérifier `prompts/PATHS.md` pour les variables
3. Adapter les chemins hardcodés vers des variables

### Redis ne démarre pas

```bash
# Vérifier le statut
redis-cli ping

# Démarrer manuellement
redis-server --daemonize yes

# Ou via Docker
docker run -d --name redis -p 127.0.0.1:6379:6379 redis:7-alpine
```

---

## Historique des versions

| Version | Date | Changements majeurs |
|---------|------|---------------------|
| v2.1 | 2026-01 | Bridge Redis Streams, CLI tools, healthcheck |
| v2.0 | 2026-01 | Version initiale, architecture multi-agents |

---

*Pour signaler un problème de mise à jour : https://github.com/OlesVanHermann/multi-agent/issues*
