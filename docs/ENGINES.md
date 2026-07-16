# Moteurs Claude Code et Codex CLI

Depuis la version 3.1.0, le modèle est l’unique sélecteur de moteur :

- `claude-*` lance Claude Code ;
- `gpt-*` lance OpenAI Codex CLI.

Le dashboard ne demande donc aucun choix de CLI. Un changement de modèle ne
change ni le répertoire de prompts, ni les fichiers de mémoire, ni
`.history`, ni l’identité Redis de l’agent.

## Profils

Les huit slots visibles sont neutres : `login1a` à `login4b`. Selon le modèle,
`login2b` devient automatiquement `claude2b` ou `codex2b`. Chaque répertoire
Codex doit être connecté séparément :

```bash
source setup/login_create.sh codex1a codex1b codex2a codex2b \
  codex3a codex3b codex4a codex4b
```

Choisir **Sign in with ChatGPT**. Le démarrage refuse une authentification par
clé API, supprime `OPENAI_API_KEY` et `CODEX_API_KEY` de l’environnement et
force `forced_login_method=chatgpt`.

## Cycle interactif commun

Pour les deux moteurs, `agent.sh` crée le tmux, attend que le TUI soit prêt,
envoie `/model <identifiant>`, confirme le menu, démarre le même bridge puis
injecte le même prompt `deviens agent` (ou la même liste de fichiers x45/z21).
Codex est lancé avec `--dangerously-bypass-approvals-and-sandbox`; aucun
`codex exec`, JSONL ou appel API n’est utilisé.

Les états web sont dérivés de `markers.claude.yaml` ou
`markers.codex.yaml`. La saisie web continue d’utiliser les mêmes opérations
tmux `send-keys` et la communication inter-agent conserve les mêmes streams
Redis.

## Effort et reasoning

Le dashboard conserve trois niveaux neutres dans les fichiers `.effort` :

| Interface | Niveau TUI |
|---|---|
| `L` | `medium` |
| `M` | `high` |
| `H` | `xhigh` / Extra high |

Les nouveaux clones livrent `prompts/default.effort` à `H`. Sur un projet
existant, `upgrade.sh` préserve `prompts/` et ne crée ni ne remplace ce fichier :
l'absence reste néanmoins interprétée comme `H` par l'interface et le moteur.

Avant le chargement du prompt agent, Claude reçoit `/model <identifiant>` puis
`/effort <niveau>`. Codex CLI 0.144.4 est piloté par le picker `/model`, qui
sélectionne successivement le modèle puis le niveau de raisonnement : les
arguments directs de `/model` seraient interprétés comme un prompt. Le même
fichier `.effort` est donc réutilisé lors d'un changement de modèle.

Un changement depuis le dashboard est aussi appliqué à chaud si la session
existe et que l'agent est libre. Sinon, le fichier est conservé et prendra
effet au prochain démarrage.
