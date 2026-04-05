# HOW TO PATCH — Pousser des fixes entre machines

## Principe

Chaque machine a deux repertoires :

| Repertoire | Role |
|-----------|------|
| `~/multi-agent/` | Working copy (on code ici, agents tournent ici) |
| `~/multi-agent-git/` | Clone git propre (sert uniquement a pousser des patches) |

On ne pousse **jamais** depuis le working copy. On copie les fichiers modifies dans `multi-agent-git/`, on commit sur une branche `patch/`, et on pousse.

---

## Architecture

```
┌──────────────────────┐         ┌──────────────────────┐
│ MACHINE A (ex: mx23) │         │ MACHINE B (ex: mx9)  │
│                      │         │                      │
│ ~/multi-agent/       │         │ ~/multi-agent/       │
│   (working copy)     │         │   (working copy)     │
│                      │         │                      │
│ ~/multi-agent-git/   │─push──► │ ~/multi-agent.git    │
│   (clone propre)     │  SSH    │   (bare repo)        │
└──────────────────────┘         └──────────────────────┘
                                          │
                                    post-receive
                                          │
                                          ▼
                                 ~/multi-agent/
                                   git fetch + cherry-pick
                                          │
                                          ▼
                                 github.com (release)
```

---

## Setup (une fois par machine)

### Cote emetteur (la machine qui pousse)

```bash
# Cloner le repo propre
git clone https://github.com/OlesVanHermann/multi-agent.git ~/multi-agent-git

# Ajouter le remote de la machine cible
cd ~/multi-agent-git
git remote add mx9 ubuntu@mx9:/home/ubuntu/multi-agent.git
```

### Cote recepteur (la machine qui recoit)

```bash
# Creer le bare repo (si pas deja fait)
git clone --bare https://github.com/OlesVanHermann/multi-agent.git ~/multi-agent.git

# Hook post-receive (auto-fetch dans le working repo)
cat > ~/multi-agent.git/hooks/post-receive << 'EOF'
#!/bin/bash
echo "$(date) | received push" >> ~/multi-agent.git/push.log
cd ~/multi-agent && git fetch hub 2>&1 >> ~/multi-agent.git/push.log
EOF
chmod +x ~/multi-agent.git/hooks/post-receive

# Ajouter le bare repo comme remote dans le working repo
cd ~/multi-agent
git remote add hub ~/multi-agent.git
```

---

## Pousser un patch

### Etape 1 : Preparer (Claude Code fait ca)

```bash
# Copier les fichiers modifies
cp ~/multi-agent/scripts/agent-bridge/agent.py ~/multi-agent-git/scripts/agent-bridge/

# Creer la branche + commit
cd ~/multi-agent-git
git checkout -B patch/mx23/fix-description main
git add -A
git commit -m "fix: description du changement"
```

### Etape 2 : Pousser (l'utilisateur fait ca)

```bash
cd ~/multi-agent-git && git push mx9 patch/mx23/fix-description
```

### Etape 3 : Recevoir et appliquer (sur la machine cible)

```bash
cd ~/multi-agent

# Voir les patches en attente
git fetch hub
git branch -r | grep hub/patch

# Inspecter
git diff --stat main..hub/patch/mx23/fix-description

# Appliquer
git cherry-pick --no-commit hub/patch/mx23/fix-description
git diff --cached --stat   # verifier
git commit -m "fix: description"

# Nettoyer
git push hub --delete patch/mx23/fix-description
```

---

## Convention de nommage

```
patch/{machine-source}/{description-slug}

Exemples :
  patch/mx23/v2.5.1-autoinit-history
  patch/mx9/fix-websocket-timeout
  patch/mac1/add-streaming-agent
```

---

## Regles pour Claude Code

Quand l'utilisateur demande de pousser un patch :

1. **Copier les fichiers modifies** dans `~/multi-agent-git/`
2. **Creer la branche + commit** :
   ```bash
   cd ~/multi-agent-git
   git checkout -B patch/{machine}/{slug} main
   git add fichiers...
   git commit -m "fix: description"
   ```
3. **Donner UNE SEULE commande** a l'utilisateur :
   ```
   cd ~/multi-agent-git && git push {remote} patch/{machine}/{slug}
   ```

**Ne PAS :**
- Demander a l'utilisateur de creer la branche ou commiter
- Donner une chaine de commandes
- Expliquer le process
- Pousser sur `main` directement

---

## Regles pour l'operateur (reception)

1. **Toujours inspecter** avant cherry-pick : `git diff --stat`
2. **Cherry-pick --no-commit** puis verifier le staged
3. **Signaux d'alerte** : suppressions massives, milliers de fichiers
4. **Si un patch est casse** : extraire les fichiers bons avec `git show branch:path > path`
5. **Supprimer les branches patch** apres integration
6. **Push GitHub = humain** (passphrase SSH)

---

## Alternative : patch script

Pour les machines sans bare repo, un script `patch/v*.sh` peut etre envoye directement :

```bash
scp patch/v2.5.1-fixes.sh mx9:~/multi-agent/patch/
ssh mx9 'cd ~/multi-agent && bash patch/v2.5.1-fixes.sh'
```

Les scripts patch sont idempotents (detectent si deja applique).

---

## Release vers GitHub

```bash
cd ~/multi-agent
git tag -a vX.Y.Z -m "vX.Y.Z - Description"
git push origin main --tags   # humain avec passphrase SSH
```

---

## Scripts

| Script | Role |
|--------|------|
| `patch/sync-to-git.sh` | Sync `~/multi-agent/` vers `~/multi-agent-git/` (bulk) |
| `patch/hub-receive.sh` | Lister les patches en attente |
| `patch/hub-cherry-pick.sh` | Cherry-pick un patch dans main |
| `patch/hub-release.sh` | Tag + push GitHub |
| `patch/v*.sh` | Patch scripts (applicables sans git) |
