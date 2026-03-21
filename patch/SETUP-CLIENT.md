# Setup Mac — Machine cliente

## Prérequis

- Git installé
- Clé SSH configurée pour le hub : `ssh ubuntu@hub.example.com` doit fonctionner
- Claude Code installé

## 1. Répertoire de travail

```bash
# Cloner ou copier multi-agent
git clone https://github.com/YOUR-ORG/multi-agent.git ~/multi-agent
cd ~/multi-agent

# Configurer les secrets
cp setup/secrets.cfg scripts/.env
# Éditer scripts/.env avec les vraies valeurs
```

## 2. Répertoire git (pour les patches)

```bash
# Cloner le framework git clean
git clone https://github.com/YOUR-ORG/multi-agent.git ~/multi-agent-git
cd ~/multi-agent-git

# Ajouter le remote hub
git remote add hub ubuntu@hub.example.com:/home/ubuntu/multi-agent.git

# Vérifier
git remote -v
# hub    ubuntu@hub.example.com:/home/ubuntu/multi-agent.git (fetch)
# hub    ubuntu@hub.example.com:/home/ubuntu/multi-agent.git (push)
# origin https://github.com/YOUR-ORG/multi-agent.git (fetch)
# origin https://github.com/YOUR-ORG/multi-agent.git (push)
```

## 3. Identité git

```bash
git config --global user.name "YOUR-ORG"
git config --global user.email "you@example.com"
```

**Important** : les agents Claude commitent avec le co-auteur `Co-Authored-By: Claude Sonnet 4.6` mais l'auteur doit rester `YOUR-ORG`.

## 4. Profils Claude Code

```bash
# Créer les profils (authentification interactive requise)
cd ~/multi-agent
source setup/login_create.sh claude1a claude1b claude2a claude2b

# Les profils sont créés dans login/
# Les alias sont ajoutés dans ~/.bashrc_claude
source ~/.bashrc_claude

# Utiliser un profil spécifique
claude1a   # = CLAUDE_CONFIG_DIR=~/multi-agent/login/claude1a claude --dangerously-skip-permissions
```

## 5. Tester la connexion hub

```bash
cd ~/multi-agent-git
git fetch hub
git branch -r | grep hub/
```

## 6. Premier patch

```bash
# Faire des modifications dans ~/multi-agent/

# Générer les checksums (macOS utilise md5, Linux utilise md5sum)
cd ~/multi-agent
git ls-files core docs scripts web | xargs md5 > file.md5

# Pousser le patch
./patch/sync-to-git.sh "ma-premiere-modification"

# Résultat affiché :
# cd ~/multi-agent-git && git push hub patch/project/ma-premiere-modification
```

## Structure des deux répertoires

```
~/multi-agent/          ← WORKING COPY (code + projet)
  scripts/.env          ← secrets (gitignored)
  login/claude1a/       ← profil Claude1a (gitignored)
  project/              ← code du projet (gitignored)
  prompts/              ← prompts agents (gitignored dans multi-agent-git)

~/multi-agent-git/      ← GIT CLEAN (patches framework seulement)
  remote hub  → hub
  remote origin → GitHub
  patch/ (branche) → jamais sur main directement
```
