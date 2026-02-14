# Pipeline Git Multi-Agent : Mac → mx9 → GitHub

## Architecture

```
┌─────────────────────┐    ┌─────────────────────┐
│ MAC 1 (claude2)     │    │ MAC 2 (claude3)     │
│                     │    │                     │
│ ~/multi-agent/      │    │ ~/multi-agent/      │
│   (working copy)    │    │   (working copy)    │
│                     │    │                     │
│ ~/multi-agent-git/  │    │ ~/multi-agent-git/  │
│   (repo git clean)  │    │   (repo git clean)  │
└────────┬────────────┘    └────────┬────────────┘
         │ git push hub              │ git push hub
         │ patch/projet/fix-xxx      │ patch/projet/fix-yyy
         ▼                           ▼
┌──────────────────────────────────────────────────────────┐
│ MX9 (ubuntu@mx9.di2amp.com)                              │
│                                                           │
│ /home/ubuntu/multi-agent.git       ← BARE REPO (réception│
│   hooks/post-receive → push.log      des patches)        │
│   auto-fetch dans working repo                            │
│                                                           │
│ /home/ubuntu/multi-agent/          ← WORKING REPO        │
│   remote hub    = multi-agent.git (local)                 │
│   remote origin = github.com (SSH)                        │
│   → triage des patches (humain)                           │
│   → cherry-pick sélectif (pas de merge aveugle)           │
│   → préparation des releases                              │
│   → push vers GitHub (humain avec passphrase SSH)         │
│                                                           │
│ /home/ubuntu/multi-agent-inception/ ← TEST BROKER         │
│   MA_PREFIX=mi (isolé)                                    │
│   rsync depuis multi-agent/ après chaque release          │
└────────────────────┬─────────────────────────────────────┘
                     │ git push origin main --tags
                     │ (humain avec passphrase SSH)
                     ▼
          github.com/OlesVanHermann/multi-agent
```

---

## Répertoires par machine

### Mac 1 / Mac 2

| Répertoire | Rôle |
|-----------|------|
| `~/multi-agent/` | Working copy avec le projet en cours (on code ici) |
| `~/multi-agent-git/` | Clone git clean pour pousser les patches vers mx9 |
| `~/multi-agent/scripts/sync-to-git.sh` | Script qui sync `~/multi-agent/` → `~/multi-agent-git/` et push |

### mx9 (serveur central)

| Répertoire | Rôle |
|-----------|------|
| `/home/ubuntu/multi-agent.git` | Bare repo — point d'arrivée des patches (SSH) |
| `/home/ubuntu/multi-agent/` | **Working repo principal** — merge, release, push GitHub |
| `/home/ubuntu/multi-agent-inception/` | Copie de test — rsync après chaque release |

---

## Pipeline complet

### Étape 1 : Mac — Créer et pousser un patch

```bash
# Sur le Mac, dans ~/multi-agent/ (là où on code)
cd ~/multi-agent

# 1. Générer les checksums MD5 (vérification d'intégrité du sync)
git ls-files core docs examples infrastructure scripts upgrade.sh upgrades web \
  | xargs md5 > file.md5
# IMPORTANT: utiliser git ls-files (respecte .gitignore)
# PAS find (inclut node_modules/, dist/, __pycache__/)

# 2. Sync + push le patch (file.md5 est inclus automatiquement)
./scripts/sync-to-git.sh "description-du-fix"
```

**Setup initial (une fois par Mac) :**
```bash
git clone https://github.com/OlesVanHermann/multi-agent.git ~/multi-agent-git
cd ~/multi-agent-git
git remote add hub ubuntu@mx9.di2amp.com:/home/ubuntu/multi-agent.git
```

---

### Étape 2 : mx9 — Réception automatique

Quand un `git push hub` arrive sur le bare repo, le hook `post-receive` :
1. Log dans `/home/ubuntu/multi-agent.git/push.log`
2. `git fetch hub` dans `/home/ubuntu/multi-agent/` (async)

La branche `hub/patch/NOM_PROJET/description` apparaît automatiquement dans le working repo.

---

### Étape 3 : mx9 — Triage et cherry-pick des patches

**IMPORTANT : Ne JAMAIS cherry-pick aveuglément. Toujours inspecter d'abord.**

```bash
cd /home/ubuntu/multi-agent

# Voir les patches en attente
git fetch hub
git ls-remote hub 'refs/heads/patch/*'

# Inspecter un patch AVANT de l'appliquer
git diff --stat main..hub/patch/NOM_PROJET/description
# ⚠️ SIGNAUX D'ALERTE d'un sync cassé :
#   - Des milliers de suppressions (-32000 lines)
#   - Des fichiers supprimés qui ne devraient pas l'être
#   - file.md5 avec 2000+ lignes (inclut node_modules/dist)

# Voir le vrai changement (exclure le bruit)
git diff --stat main..hub/patch/NOM_PROJET/description \
  -- ':!file.md5' ':!framework.md5' ':!scripts/good_start_prompt.md' ':!.gitignore'

# Voir le diff d'un fichier spécifique
git diff main..hub/patch/NOM_PROJET/description -- chemin/vers/fichier.py
```

**Appliquer un patch propre :**
```bash
# Cherry-pick sans commit (pour inspecter)
git cherry-pick --no-commit hub/patch/NOM_PROJET/description

# Retirer le bruit (file.md5, framework.md5, etc.)
git reset HEAD file.md5 framework.md5 scripts/good_start_prompt.md .gitignore 2>/dev/null
git checkout -- .gitignore 2>/dev/null

# Vérifier ce qui reste (seulement les vrais changements)
git diff --cached --stat

# Commit
git commit -m "feat: description du changement"
```

**Appliquer un fichier spécifique depuis un patch cassé :**
```bash
# Quand le sync est cassé mais un fichier est bon
git show hub/patch/NOM_PROJET/description:chemin/vers/fichier.py > chemin/vers/fichier.py
git add chemin/vers/fichier.py
git commit -m "fix: description"
```

**Vérification MD5 (si file.md5 est propre) :**
```bash
# Convertir format BSD → GNU et vérifier
sed 's/^MD5 (\(.*\)) = \(.*\)$/\2  \1/' file.md5 | md5sum -c | grep -v ': OK$'
# Si des fichiers échouent → le sync était cassé
```

**Nettoyer après intégration :**
```bash
git push hub --delete patch/NOM_PROJET/description
```

---

### Étape 4 : mx9 — Release

```bash
cd /home/ubuntu/multi-agent

# Tag la release
git tag -a vX.Y.Z -m "vX.Y.Z - Description"

# Push sur hub
git push hub main --tags

# Mettre à jour inception
rsync -av --exclude='__pycache__/' --exclude='node_modules/' \
  --exclude='dist/' --exclude='.pytest_cache/' --exclude='venv/' \
  --exclude='*.pyc' --exclude='dump.rdb' \
  core/ /home/ubuntu/multi-agent-inception/core/
# (répéter pour scripts/ web/ docs/ etc.)
# Ou copier les fichiers modifiés individuellement :
cp scripts/fichier.sh /home/ubuntu/multi-agent-inception/scripts/

# L'humain pousse sur GitHub (nécessite passphrase SSH)
git push origin main --tags
```

---

### Étape 5 : Mac — Récupérer la release

```bash
cd ~/multi-agent-git
git pull hub main --rebase
```

---

## Remotes

### Sur les Mac

| Remote | URL | Usage |
|--------|-----|-------|
| `hub` | `ubuntu@mx9.di2amp.com:/home/ubuntu/multi-agent.git` | Push patches |
| `origin` | `github.com/OlesVanHermann/multi-agent.git` | Pull releases |

### Sur mx9 (`/home/ubuntu/multi-agent/`)

| Remote | URL | Usage |
|--------|-----|-------|
| `hub` | `/home/ubuntu/multi-agent.git` (local bare repo) | Recevoir les patches |
| `origin` | `git@github.com:OlesVanHermann/multi-agent.git` | Push releases (humain + passphrase) |

---

## Convention de nommage des branches patch

```
patch/{NOM_PROJET}/{description}

Exemples :
  patch/onlyoffice/fix-timeout
  patch/inception/add-ma-prefix
  patch/project/sync-chrome-bridge
```

---

## Règles pour les agents Mac

1. **Ne JAMAIS pousser directement sur `main`** — toujours via une branche `patch/`
2. **Ne JAMAIS modifier `~/multi-agent-git/` manuellement** — utiliser `./scripts/sync-to-git.sh`
3. **Un patch = un sujet** — ne pas mélanger des fixes différents
4. **Description courte en slug** : `fix-timeout`, `add-prefix`, `update-bridge`
5. **Après le push** : mx9 reçoit automatiquement, pas besoin de notifier
6. **Ne JAMAIS exécuter de commandes SSH sur mx9** — les agents Mac poussent des patches, c'est tout
7. **Ne JAMAIS créer son propre sync-to-git.sh** — utiliser `./scripts/sync-to-git.sh` du repo
8. **Ne JAMAIS cherry-pick ou release sur mx9 via SSH** — c'est le rôle de l'opérateur mx9
9. **Générer file.md5 avec `git ls-files | xargs md5`** — PAS avec `find` (inclut le junk)
10. **Auteur git = OlesVanHermann** — jamais Claude/claude comme auteur

---

## Règles pour l'opérateur mx9

1. **Toujours inspecter un patch avant cherry-pick** — `git diff --stat` d'abord
2. **Exclure le bruit** des patches : `file.md5`, `framework.md5`, `good_start_prompt.md`, `.gitignore`
3. **Cherry-pick --no-commit** puis nettoyer le staged avant de commiter
4. **Un sync cassé se reconnaît à** : suppressions massives, milliers de fichiers changés, file.md5 > 200 lignes
5. **Si un patch est cassé** : extraire seulement les fichiers utiles avec `git show branch:path > path`
6. **Après chaque release** : copier les fichiers modifiés dans `-inception/`
7. **Push GitHub = humain** (passphrase SSH requise, pas automatisable)
8. **Supprimer les branches patch** après intégration : `git push hub --delete patch/...`
9. **Comparer les file.md5** de plusieurs Macs avec un script Python pour trouver les vrais changements
10. **Auteur des commits = OlesVanHermann** — nettoyer si un agent a commité avec son propre nom

---

## Problèmes connus et solutions

### Sync cassé (agent crée son propre sync-to-git.sh)

**Symptôme** : Patch avec des milliers de suppressions, arborescence aplatie.
**Cause** : L'agent a créé un script `~/sync-to-git.sh` maison au lieu d'utiliser `./scripts/sync-to-git.sh`.
**Solution** : Rejeter le patch entier. Dire à l'agent d'utiliser le bon script.

### file.md5 avec 2000+ lignes

**Symptôme** : `file.md5` contient `node_modules/`, `dist/`, `__pycache__/`.
**Cause** : Généré avec `find` au lieu de `git ls-files`.
**Solution** : Régénérer avec `git ls-files ... | xargs md5 > file.md5`.

### Agent pousse directement sur hub/main

**Symptôme** : Nouveaux commits sur `hub/main` sans branche patch.
**Cause** : L'agent a poussé sur main au lieu de créer une branche `patch/`.
**Solution** : Inspecter les commits, garder les bons, reset si nécessaire.

### Agent exécute des commandes SSH sur mx9

**Symptôme** : Cherry-pick, `rm -rf`, release, tag créés depuis le Mac via SSH.
**Cause** : L'agent contourne le pipeline et opère directement sur mx9.
**Solution** : `git reset --hard` au dernier bon commit. Supprimer les tags bogus. Rappeler la règle 6.

### Bruit dans les patches

**Symptôme** : Chaque patch inclut `file.md5`, `framework.md5`, `good_start_prompt.md`, diff `.gitignore`.
**Cause** : Ces fichiers existent dans le working copy du Mac mais pas sur mx9.
**Solution** : Après `cherry-pick --no-commit`, toujours faire `git reset HEAD` sur ces fichiers.

### Auteur Claude dans les commits

**Symptôme** : `git log` montre `Claude <claude@Claude1.local>` comme auteur.
**Cause** : Le Mac n'a pas configuré `user.name`/`user.email` correctement.
**Solution** : Sur le Mac :
```bash
git config --global user.name "OlesVanHermann"
git config --global user.email "octave.klaba@ovh.com"
```
Pour nettoyer l'historique existant : `git checkout --orphan fresh && git add -A && git commit` avec le bon auteur.

---

## Scripts

| Script | Machine | Répertoire | Rôle |
|--------|---------|-----------|------|
| `scripts/sync-to-git.sh` | Mac | `~/multi-agent/` | Sync framework → `~/multi-agent-git/` + push patch |
| `scripts/hub-receive.sh` | mx9 | `/home/ubuntu/multi-agent/` | Lister les patches en attente |
| `scripts/hub-cherry-pick.sh` | mx9 | `/home/ubuntu/multi-agent/` | Cherry-pick un patch dans main |
| `scripts/hub-release.sh` | mx9 | `/home/ubuntu/multi-agent/` | Tests + tag + push GitHub |
| `hooks/post-receive` | mx9 | `/home/ubuntu/multi-agent.git/` | Log + auto-fetch à la réception |

---

## Flux complet (exemple)

```
1. Mac1 : développeur corrige un bug dans web/backend/server.py

2. Mac1 : cd ~/multi-agent
         git ls-files core docs examples infrastructure scripts upgrade.sh upgrades web \
           | xargs md5 > file.md5
         ./scripts/sync-to-git.sh "fix-websocket-timeout"
   → crée patch/project/fix-websocket-timeout
   → push sur le bare repo mx9

3. mx9 : post-receive hook log + fetch
   → hub/patch/project/fix-websocket-timeout visible

4. mx9 : inspecter le patch
         git diff --stat main..hub/patch/project/fix-websocket-timeout
   ⚠️ Si >1000 lignes de suppressions → sync cassé → rejeter

5. mx9 : cherry-pick sélectif
         git cherry-pick --no-commit hub/patch/project/fix-websocket-timeout
         git reset HEAD file.md5 framework.md5 2>/dev/null
         git diff --cached --stat   # vérifier
         git commit -m "fix: websocket timeout"

6. mx9 : tag + push hub
         git tag -a v2.5.1 -m "v2.5.1"
         git push hub main --tags

7. mx9 : mettre à jour inception
         cp web/backend/server.py /home/ubuntu/multi-agent-inception/web/backend/

8. mx9 : nettoyer la branche patch
         git push hub --delete patch/project/fix-websocket-timeout

9. humain : git push origin main --tags   (passphrase SSH)

10. Mac1 : cd ~/multi-agent-git && git pull hub main --rebase
    → récupère la release
```
