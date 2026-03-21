# Mono Agent — Guide complet

Le format **mono** est le type d'agent le plus simple : un seul fichier `.md` dans un répertoire dédié.

---

## Quand utiliser le format mono

| Format | Quand l'utiliser |
|--------|------------------|
| **mono** | Agent à tâche unique, workflow simple, pas d'auto-amélioration |
| **x45** | Agent auto-améliorant avec boucles de feedback (system + memory + methodology) |
| **z21** | Workflows complexes avec sous-contextes satellites |

Le format mono convient à la majorité des agents de production : Masters (1XX), Developers (3XX), Integrators (4XX), Testers (5XX), Releasers (6XX).

---

## Structure d'un agent mono

```
prompts/{ID}-{nom}/
├── agent.type            → ../agent_mono.type   # Marqueur de type (symlink)
├── {ID}-{nom}.md         # Le prompt principal (fichier réel)
├── {ID}-{nom}.history    # Vide au départ (placeholder)
├── {ID}-{nom}.login      → ../default.login     # Profil Claude à utiliser
└── {ID}-{nom}.model      → ../default.model     # Modèle à utiliser
```

**Exemple concret** (`prompts/150-create-mono/`) :

```
150-create-mono/
├── agent.type            → ../agent_mono.type
├── 150-create-mono.md    # 3.6K — prompt de création d'agents mono
├── 150-create-mono.history   # 0B — vide
├── 150-create-mono.login → ../default.login
└── 150-create-mono.model → ../default.model
```

---

## Fichiers marqueurs dans `prompts/`

Ces trois fichiers vides à la racine de `prompts/` servent de cibles aux symlinks `agent.type` :

```
prompts/
├── agent_mono.type    # Vide — cible des agents mono
├── agent_x45.type     # Vide — cible des agents x45
├── agent_z21.type     # Vide — cible des agents z21
├── default.login      # Profil Claude par défaut (ex: "claude1a")
├── default.model      # Modèle par défaut (ex: "claude-sonnet-4-6")
└── ...
```

Le symlink `agent.type` est toujours **relatif** (`../agent_mono.type`) et jamais un chemin absolu.

---

## Fichiers `.login` et `.model`

Ces fichiers contiennent une **chaîne de texte simple** (le nom du profil ou du modèle) :

```bash
cat prompts/default.login   # → "claude1a"
cat prompts/default.model   # → "claude-sonnet-4-6"
```

Chaque agent peut avoir son propre login/modèle via symlink :

```bash
# Utiliser le login par défaut
ln -sf ../default.login 150-create-mono.login

# Ou un login spécifique
ln -sf ../claude2b.login 150-create-mono.login
```

**Résolution** (par `resolve_config()` dans `agent.sh`) :
1. `prompts/{ID}-{nom}/{ID}.login` — spécifique à cet agent (dans le répertoire)
2. `prompts/{ID}.login` — flat dans `prompts/`
3. `prompts/default.login` — fallback système

---

## Le fichier `.history`

Fichier vide créé à l'initialisation (`touch`). C'est un **placeholder** — le bridge maintient l'historique des échanges en mémoire (commande `/history`), pas dans ce fichier.

---

## Démarrage

### Via `agent.sh`

```bash
# Démarrer un agent mono
./scripts/agent.sh start 150

# Démarrer tous les agents (auto-détection)
./scripts/agent.sh start all
```

### Ce qui se passe au démarrage

1. `agent.sh` crée une session tmux `{MA_PREFIX}-agent-{ID}` (ex : `A-agent-150`)
2. Fenêtre `0` : `claude --dangerously-skip-permissions` (avec le bon `CLAUDE_CONFIG_DIR` si `.login` est défini)
3. Fenêtre `bridge` : `python3 scripts/agent-bridge/agent.py {ID}`

Le bridge **injecte automatiquement** le prompt au démarrage :
```
deviens agent prompts/150-create-mono/150-create-mono.md
```

En cas de compaction de contexte par Claude, le même prompt est **re-injecté automatiquement** (sans `/reset`) pour préserver la session.

---

## Détection automatique par `agent.sh`

`agent.sh start all` scanne `prompts/[0-9][0-9][0-9]*` et lit `agent.type` :

```bash
if [ -L "$agent_dir/agent.type" ]; then
    agent_type=$(basename "$(readlink "$agent_dir/agent.type")" .type | sed 's/agent_//')
fi

if [ "$agent_type" = "mono" ]; then
    # Session = bare 3-digit ID
    SESSION="${MA_PREFIX}-agent-${base_id}"
fi
```

Un agent mono est identifié par son **ID nu** (3 chiffres), contrairement aux agents x45/z21 qui utilisent un format composé (`{ID}-{ID}` pour le principal, `{ID}-{satellite}` pour les satellites).

---

## Communication

```bash
# Envoyer un message à l'agent 150
./scripts/send.sh 150 "CREER mono 910-project-memory pour gérer la mémoire persistante"

# Voir les réponses en temps réel
./scripts/watch.sh 150

# Attacher à la session tmux
tmux attach -t A-agent-150
```

**Redis Streams** (format direct) :
```bash
redis-cli XADD "A:agent:150:inbox" '*' \
    prompt "CREER mono 910-project-memory pour ..." \
    from_agent "100" \
    timestamp "$(date +%s)"
```

---

## Anatomie d'un prompt mono

Structure recommandée (basée sur `150-create-mono.md`) :

```markdown
# {ID} — {Nom lisible} — {Description courte}

## Identité
- **ID** : {ID}
- **Type** : mono
- **Rôle** : {description}

## Quand tu es appelé

{Décrire le déclencheur : quel message, de qui (utilisateur / Master 100 / autre agent)}

---

## Ta mission

{Étapes de travail dans l'ordre, concrètes et opérationnelles}

---

## Règles
- JAMAIS `rm` — toujours `mv` vers `$REMOVED/`
- Pas d'emoji dans le code, les commits, les messages

## Complétion

\```bash
$BASE/scripts/send.sh 100 \
  prompt "FROM:{ID}|DONE {description}" \
  from_agent "{ID}" timestamp "$(date +%s)"
\```
```

**Principes** :
- Pas un squelette vide — un prompt opérationnel complet
- Pas de contenu projet-spécifique dans les agents génériques
- Toujours notifier le Master 100 (ou l'émetteur) à la fin

---

## Créer un agent mono

### Via l'agent 150 (recommandé)

```bash
./scripts/send.sh 150 "CREER mono 400-merge pour intégrer les fichiers produits par les agents 3XX"
```

Options facultatives :
```bash
./scripts/send.sh 150 "CREER mono 620-release pour taguer et publier une release GitHub login:claude2a model:claude-opus-4-6"
```

### Manuellement

```bash
BASE="/home/ubuntu/multi-agent"
ID="400"
NOM="merge"
DIR="$BASE/prompts/${ID}-${NOM}"
LOGIN="default"  # ou claude2a, claude1b, etc.
MODEL="default"  # ou claude-sonnet-4-6, etc.

mkdir -p "$DIR"
cd "$DIR"

# Marqueur de type (obligatoire)
ln -sf ../agent_mono.type agent.type

# Placeholder history
touch ${ID}-${NOM}.history

# Symlinks login et model
ln -sf ../${LOGIN}.login ${ID}-${NOM}.login
ln -sf ../${MODEL}.model ${ID}-${NOM}.model

# Créer le prompt (fichier réel)
$EDITOR ${ID}-${NOM}.md
```

**Vérification** :
```bash
ls -la "$DIR/"
# Vérifier que les symlinks ne sont pas cassés
find "$DIR/" -type l | while read link; do
    test -e "$link" || echo "BROKEN SYMLINK: $link"
done
```

---

## Conventions de nommage

| Élément | Convention | Exemple |
|---------|-----------|---------|
| Répertoire | `{ID}-{kebab-case}` | `150-create-mono` |
| Fichier prompt | `{ID}-{kebab-case}.md` | `150-create-mono.md` |
| ID agent | 3 chiffres, plage CLAUDE.md | `150` (100-199 = Masters) |
| Nom | slug kebab-case, descriptif | `create-mono`, `merge`, `release` |

---

## Arrêter un agent

```bash
# Arrêter un agent
./scripts/agent.sh stop 150

# Arrêter tous les agents (sauf 000)
./scripts/agent.sh stop all
```

---

## Différences avec x45

| Aspect | mono | x45 |
|--------|------|-----|
| Fichiers | 1 `.md` | 3 fichiers (`system.md`, `memory.md`, `methodology.md`) |
| Auto-amélioration | Non | Oui (boucles de feedback) |
| ID session | `{ID}` (ex: `150`) | `{ID}-{ID}` (ex: `352-352`) + satellites |
| Auto-init bridge | `deviens agent {path}` | `Lis ces fichiers dans l'ordre...` |
| Complexité | Simple | Avancée |

---

*Voir aussi : [`docs/X45-METHODOLOGY.md`](X45-METHODOLOGY.md) — format x45 | [`docs/BRIDGE.md`](BRIDGE.md) — communication Redis*
