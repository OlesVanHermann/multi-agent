# FIRST_HERE — Installation locale de multi-agent

Tu es l'agent chargé d'installer multi-agent sur cette machine.
Lis et exécute chaque étape dans l'ordre.

Les étapes marquées **[HUMAIN]** requièrent une interaction utilisateur — arrête-toi, explique ce qu'il faut faire, et attends confirmation avant de continuer.

---

## Statistiques d'installation obligatoires

Chronométrer chaque étape avec une horloge monotone et annoncer sa durée dès
qu'elle se termine. Séparer le temps actif du temps d'attente humaine
(authentification, mot de passe, téléchargement externe).

Conserver le bilan dans `logs/action-timings.tsv` :

```text
timestamp	action	phase	duration_seconds	status	details
2026-07-26T12:00:00Z	install	prerequisites	8	OK	6 commandes vérifiées
```

Conserver également une copie immuable de chaque installation sous
`logs/action-timings/<YYYYMMDDTHHMMSSffffffZ>-install.tsv`. Le préfixe est en
UTC et comporte six chiffres de fraction de seconde ; une exécution ne réécrit
jamais la copie d'une précédente. Cette convention s'applique aux logs et aux
plans d'installation archivés, jamais aux fichiers de prompts.

Les plans métier créés après l'installation suivent
`docs/PLAN-LIFECYCLE.md` : préfixe UTC attribué une seule fois à la création,
nom stable dans TODO/DOING/DONE et journal des transitions. Aucun prompt n'est
renommé.

Le compte rendu final contient au minimum : prérequis, dépendances,
infrastructure, profils/authentification, création ou migration des agents,
checks, attente externe et total. Toute durée oubliée est marquée
`NON MESURÉ`, jamais estimée après coup.

---

## Persistance des sessions Codex multi-profils

Après l'authentification séparée des comptes Codex, exécuter :

```bash
python3 scripts/audit-codex-sessions.py --apply
```

L'outil détecte comme actifs les profils référencés par un agent ou possédant
déjà un `auth.json`. Il conserve les autres paramètres et impose uniquement
`forced_login_method = "chatgpt"` et
`cli_auth_credentials_store = "file"`. Il applique `700` au répertoire et
`600` à `config.toml`/`auth.json`, puis vérifie chaque `CODEX_HOME`.

Le rapport n'expose que le mode d'authentification, la présence booléenne du
refresh token et `last_refresh`, jamais un token, hash ou identifiant de
compte. Un doublon produit seulement les commandes `codex login --device-auth`
à exécuter humainement. Aucun logout/login ou service n'est lancé.

---

## Contrat de communication à installer

Avant de créer ou démarrer les agents, lire
`docs/AGENT-COMMUNICATION.md`, `prompts/AGENT.md`, `prompts/RULES.md` et
`prompts/PATHS.md`. Tout agent créé doit utiliser `scripts/send.sh` pour les
événements non terminaux et `scripts/done.sh` pour son unique terminal corrélé.
Ne recopier aucun ancien exemple contenant `FROM:` dans le texte ou un appel
direct à Redis.

Pour chaque topologie mono/x45/z21, vérifier aussi le Contradictor `NNN-2XX`
selon `docs/CONTRADICTOR.md`. Son prompt doit contenir
`Audit de l'exécution de la demande utilisateur — v3.2.7` et sa méthodologie
`Méthode d'audit utilisateur — v3.2.7`. Il distingue demande utilisateur,
instructions d'agents, échanges internes et preuves physiques.

L'installation initiale peut ensuite suivre les étapes de démarrage décrites
ci-dessous. Cette autorisation ne s'applique pas à une mise à jour d'un système
déjà actif : après upgrade, ne lancer automatiquement ni `infra.sh start` ni
`agent.sh start all`.

---

## Étape 0 — Vérifier les prérequis

```bash
git --version        # ≥ 2.30
python3 --version    # ≥ 3.10
docker --version     # Docker Desktop ou docker.io
node --version       # ≥ 18 (pour le dashboard)
tmux -V              # ≥ 3.0
claude --version     # Claude Code CLI
```

Installer les manquants :

```bash
# Claude Code (si absent) — installeur officiel
curl -fsSL https://claude.ai/install.sh | bash

# Docker sur Linux (si absent)
sudo apt-get install -y docker.io && sudo systemctl start docker && sudo usermod -aG docker $USER

# tmux / node sur Linux
sudo apt-get install -y tmux nodejs npm
```

---

## Étape 1 — Cloner le dépôt

```bash
# Choisir l'emplacement — ~/multi-agent est la convention
git clone https://github.com/OlesVanHermann/multi-agent.git ~/multi-agent
cd ~/multi-agent
```

---

## Étape 2 — Installer les dépendances Python

```bash
cd ~/multi-agent
pip install -r requirements.txt
```

---

## Étape 3 — Configurer les secrets

```bash
cp setup/secrets.cfg.template setup/secrets.cfg
```

Le fichier `setup/secrets.cfg` à remplir (c'est LE chemin sourcé par tous
les scripts — `infra.sh` refuse de démarrer Keycloak avec les valeurs par
défaut) :

```bash
KEYCLOAK_ADMIN_PASSWORD=changeme   # ← changer (mot de passe Keycloak admin)
HEALTH_TOKEN=changeme              # ← changer (token inter-services)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=                    # laisser vide si Redis local sans auth
```

**[HUMAIN]** Édite le fichier avec tes valeurs :

```bash
nano ~/multi-agent/setup/secrets.cfg
```

---

## Étape 4 — Identité git

```bash
git config --global user.name  "TonNom"
git config --global user.email "ton@email.com"
```

Les agents commitent avec un trailer `Co-Authored-By: Claude …` mais l'auteur reste ton identité.

---

## Étape 5 — Installer les alias Claude Code (.bashrc_claude)

```bash
cd ~/multi-agent
./setup/install_bashrc_claude.sh
source ~/.bashrc_claude
```

Ce script crée `~/.bashrc_claude` avec les alias multi-profils :

```bash
alias claude1a='CLAUDE_CONFIG_DIR=~/multi-agent/login/claude1a claude --dangerously-skip-permissions'
alias claude1b='CLAUDE_CONFIG_DIR=~/multi-agent/login/claude1b claude --dangerously-skip-permissions'
# ... claude2a claude2b claude3a claude3b claude4a claude4b
```

Et ajoute automatiquement dans `~/.bashrc` :
```bash
[ -f ~/.bashrc_claude ] && source ~/.bashrc_claude
```

Vérifier :
```bash
type claude1a   # → alias claude1a='...'
```

---

## Étape 6 — Créer les profils Claude Code

**[HUMAIN]** Cette étape ouvre Claude Code en mode interactif pour chaque profil.
Lance la commande, authentifie-toi, puis tape `/exit` pour chaque profil.

```bash
cd ~/multi-agent
source setup/login_create.sh claude1a claude1b
```

Le script crée :
- `login/claude1a/` et `login/claude1b/` (répertoires CLAUDE_CONFIG_DIR)
- les profils physiques `login/claude1a`, `login/codex1a`, etc. ; les agents
  sélectionnent les slots neutres `prompts/login1a.login` à `login4b.login`

Avec un seul profil, les deux agents 1a et 1b partagent la même authentification.
Avec deux profils distincts (recommandé), chaque paire d'agents a son propre compte.

---

## Étape 7 — Configurer login et modèle par défaut

```bash
cd ~/multi-agent/prompts

# Profil par défaut (remplacer claude1a par ton profil principal)
ln -sf login1a.login default.login
```

Le dépôt inclut déjà `default.model -> opus-5.model` (Claude Opus 5 par défaut).
Pour utiliser un autre modèle, mettre à jour le symlink :

```bash
# Modèles disponibles : opus-5, gpt-5-6-sol, gpt-5-6-terra, gpt-5-6-luna,
# sonnet-5, opus-4-8, opus-4-7, opus-4-6, sonnet-4-6, sonnet-4-5, haiku-4-5
ln -sf opus-5.model default.model       # → claude-opus-5
```

Convention x45/z21 : les rôles auparavant sur `fable-5` utilisent
`gpt-5-6-sol`; ceux auparavant sur `gpt-5-6-sol` utilisent `opus-5`.
L'effort livré est `M`, et le Coach utilise désormais `login1a`.

Vérifier :

```bash
ls -la prompts/default.login prompts/default.model
cat prompts/default.model    # → claude-opus-5 (ou le modèle choisi)
```

---

## Étape 8 — Créer project-config.md

```bash
cp setup/project-config.md.template project-config.md
```

Éditer au minimum :

```bash
# project-config.md
PROJECT_NAME=mon-projet
```

**[HUMAIN]** Si tu veux personnaliser davantage :

```bash
nano ~/multi-agent/project-config.md
```

---

## Étape 9 — Démarrer l'infrastructure

```bash
cd ~/multi-agent
./scripts/infra.sh start
```

Ce script démarre dans l'ordre :
1. **Redis** — container Docker `ma-redis` (port 6379)
2. **Keycloak** — container Docker `ma-keycloak` (port 8080)
3. **Dashboard web** — `http://localhost:8050`
4. **Agent 000** — dans la session tmux `agent-000`

Durée : ~30 secondes (Keycloak met du temps à démarrer).

---

## Étape 10 — Démarrer les agents

```bash
cd ~/multi-agent
./scripts/agent.sh start all
```

---

## Étape 11 — Vérifier

```bash
# Sessions tmux actives
tmux ls

# Redis répond
redis-cli ping                         # → PONG

# Dashboard accessible
curl -s http://localhost:8050/health   # → {"status":"ok",...}

# Keycloak prêt (peut prendre 1-2 min)
curl -s http://localhost:8080/health/ready
```

Attacher l'agent 000 pour voir l'activité :

```bash
tmux attach -t agent-000
# Détacher : Ctrl+B D
```

---

## Ports

| Port | Service | Notes |
|------|---------|-------|
| 6379 | Redis | Streams inter-agents |
| 8050 | Dashboard web | Interface de monitoring |
| 8080 | Keycloak | Auth (admin/changeme) |
| 9222 | CDP Bridge | Chrome DevTools, optionnel |

---

## Commandes utiles

```bash
# Arrêter tout
./scripts/infra.sh stop

# Démarrer/arrêter un agent spécifique
./scripts/agent.sh start 300
./scripts/agent.sh stop 300

# Envoyer un message à un agent
./scripts/send.sh 000 "go"

# Voir les logs d'un agent (stream temps réel)
./scripts/watch.sh 300

# Statut de tous les agents
./scripts/status.sh
```

---

## En cas de problème

| Symptôme | Vérification |
|----------|-------------|
| Redis ne démarre pas | `docker ps -a` — voir logs `ma-redis` |
| Agent 000 absent de `tmux ls` | Vérifier `prompts/default.login` pointe vers un profil existant |
| Dashboard 404 | Voir `web/backend/` — `pip install -r requirements.txt` fait ? |
| Keycloak 503 | Attendre 2 min — image lente au premier démarrage |
| `claude: command not found` | Refaire l'étape 0 — Claude Code pas dans le PATH |
| Pas de scroll dans les panes du dashboard | Vérifier qu'aucun `login/claude*/settings.json` ne contient `"tui": "fullscreen"` (l'écran alternatif vide l'historique tmux) et que `env.CLAUDE_CODE_DISABLE_MOUSE=1` y est présent, puis redémarrer les agents |
| Re-login demandé plusieurs fois par jour | Realm importé avant v3.0.7 — appliquer les durées via kcadm, voir `docs/AUTH.md` § Durées de session |

---

*Installation terminée. Envoyer `./scripts/send.sh 000 "go"` pour démarrer le pipeline.*

---

## Documentation détaillée

| Sujet | Fichier |
|-------|---------|
| Redis — Docker, ports, clés, commandes | [`setup/REDIS.md`](setup/REDIS.md) |
| Keycloak — Docker, users, realm, tokens | [`setup/KEYCLOAK.md`](setup/KEYCLOAK.md) |
| Aliases Claude Code (.bashrc_claude) | [`setup/install_bashrc_claude.sh`](setup/install_bashrc_claude.sh) |
