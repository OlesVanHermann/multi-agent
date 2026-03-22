# Setup Hub — Serveur central

Le hub est le serveur central : il reçoit les patches des machines Mac, intègre sélectivement, et publie sur GitHub.

## Prérequis

- Ubuntu 22.04+
- Git, Docker, Node.js, Python 3.10+
- Clé SSH GitHub configurée (`git@github.com` doit fonctionner)
- Redis installé et actif

## 1. Bare repo (point d'arrivée des patches)

```bash
# Créer le bare repo
mkdir -p /home/ubuntu/multi-agent.git
cd /home/ubuntu/multi-agent.git
git init --bare

# Hook post-receive : log + auto-fetch
cat > hooks/post-receive << 'HOOK'
#!/bin/bash
# Log chaque push
while read oldrev newrev refname; do
    echo "$(date -Iseconds) $refname $newrev" >> /home/ubuntu/multi-agent.git/push.log
done

# Auto-fetch dans le working repo (async)
(git fetch hub --prune 2>/dev/null) &
HOOK
chmod +x hooks/post-receive
```

## 2. Working repo (triage + release)

```bash
# Cloner depuis GitHub
git clone git@github.com:YOUR-ORG/multi-agent.git /home/ubuntu/multi-agent
cd /home/ubuntu/multi-agent

# Remotes
git remote rename origin origin             # GitHub (push release)
git remote add hub /home/ubuntu/multi-agent.git  # Bare local (recevoir patches)

# Vérifier
git remote -v
# hub    /home/ubuntu/multi-agent.git (fetch)
# hub    /home/ubuntu/multi-agent.git (push)
# origin git@github.com:YOUR-ORG/multi-agent.git (fetch)
# origin git@github.com:YOUR-ORG/multi-agent.git (push)

# Identité git
git config user.name "YOUR-ORG"
git config user.email "you@example.com"
```

## 3. Secrets

```bash
cp setup/secrets.cfg scripts/secrets.cfg
# Éditer secrets.cfg avec les vraies valeurs
nano scripts/secrets.cfg
```

## 4. Infrastructure (Docker + Keycloak + Redis)

```bash
# Installer Docker + Keycloak
./setup/install_keycloak.sh

# Vérifier Keycloak
curl -s http://localhost:8080/health/ready

# Créer les utilisateurs Keycloak
./setup/keycloak_user_create.sh dev1 MonMotDePasse
./setup/keycloak_user_create.sh dev2 MonMotDePasse

# Démarrer tout
./scripts/infra.sh start
```

## 5. Inception (environnement de test)

```bash
# Cloner depuis le working repo
rsync -av --exclude='__pycache__/' --exclude='node_modules/' \
  --exclude='*.pyc' --exclude='dump.rdb' --exclude='venv/' \
  --exclude='.git/' --exclude='login/' \
  /home/ubuntu/multi-agent/ /home/ubuntu/multi-agent-inception/

cd /home/ubuntu/multi-agent-inception
cp setup/secrets.cfg scripts/secrets.cfg
# Éditer secrets.cfg — changer les ports si besoin
nano scripts/secrets.cfg

# Démarrer avec un prefix différent pour isoler
MA_PREFIX=mi ./scripts/infra.sh start
```

## 6. Workflow quotidien

```bash
cd /home/ubuntu/multi-agent

# Voir les patches en attente
./patch/hub-receive.sh

# Intégrer un patch
./patch/hub-cherry-pick.sh hub/patch/project/fix-xxx

# Release
./patch/hub-release.sh

# Mettre à jour inception après release
rsync -av scripts/ /home/ubuntu/multi-agent-inception/scripts/
rsync -av web/ /home/ubuntu/multi-agent-inception/web/

# Push GitHub (passphrase SSH requise — humain uniquement)
git push origin main --tags
```

## Ports

| Port | Service | Requis |
|------|---------|--------|
| 8050 | Dashboard (uvicorn) | Oui |
| 8080 | Keycloak (Docker) | Oui |
| 6379 | Redis | Oui |
| 9222 | CDP Bridge (Chrome) | Optionnel |
| 80 | Reverse proxy | Optionnel |

## Structure sur le hub

```
/home/ubuntu/
├── multi-agent.git/         ← bare repo (SSH endpoint)
│   ├── hooks/post-receive   ← log + auto-fetch
│   └── push.log             ← historique des pushes
│
├── multi-agent/             ← working repo (cherry-pick + release)
│   ├── remote hub  → multi-agent.git (local)
│   └── remote origin → GitHub (SSH)
│
└── multi-agent-inception/   ← test broker (MA_PREFIX=mi)
    └── (rsync de multi-agent/ après chaque release)
```
