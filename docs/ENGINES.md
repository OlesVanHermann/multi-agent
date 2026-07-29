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

Après authentification, sécuriser et auditer la persistance :

```bash
python3 scripts/audit-codex-sessions.py --apply --all-profiles
```

Chaque compte conserve un `CODEX_HOME` distinct. L'outil impose la méthode
ChatGPT et le stockage fichier, applique les permissions `700/600/600`,
contrôle le statut et détecte les `auth.json` identiques sans afficher leur
contenu ni leur hash. Un doublon exige une réauthentification humaine avec
`codex login --device-auth`; aucun logout, login ou redémarrage n'est
automatique.

Choisir **Sign in with ChatGPT**. Le démarrage refuse une authentification par
clé API, supprime `OPENAI_API_KEY` et `CODEX_API_KEY` de l’environnement et
force `forced_login_method=chatgpt`.

## Cycle interactif commun

Pour les deux moteurs, `agent.sh` crée le tmux, attend que le TUI soit prêt,
applique explicitement le modèle demandé, démarre le même bridge puis injecte
le même prompt `deviens agent` (ou la même liste de fichiers x45/z21). Claude
accepte `/model <identifiant>` ; Codex est piloté par son picker uniquement lors
du démarrage ou d'un changement demandé.
Codex est lancé avec `--dangerously-bypass-approvals-and-sandbox`; aucun
`codex exec`, JSONL ou appel API n’est utilisé.

Les états web sont dérivés de `markers.claude.yaml` ou
`markers.codex.yaml`. La saisie web continue d’utiliser les mêmes opérations
tmux `send-keys` et la communication inter-agent conserve les mêmes streams
Redis.

## Observation du modèle sans blocage

Le bridge n'envoie jamais `/model` ou `/effort` sans argument pour consulter
l'état. Dans Claude Code, ces commandes ouvrent des pickers interactifs : les
utiliser comme sondes laisse le menu ouvert et bloque l'agent.

L'état runtime est donc relevé passivement :

- Codex expose modèle et effort dans son footer ;
- Claude est observé uniquement à partir des confirmations déjà rendues après
  un changement explicite ;
- si Claude n'expose aucune confirmation récente, la valeur runtime reste
  inconnue et la valeur configurée reste affichée séparément.

Une information inconnue ne déclenche jamais une commande TUI. `/model` et
`/effort` ne sont envoyés qu'avec l'intention de modifier la configuration.

Le sweep d'usage réutilise la vue `/status` qu'il ouvre déjà pour relever aussi
le champ `Model:`. Le même parseur couvre Claude Code et Codex, et enregistre
le modèle avec les informations du profil. Il ne faut jamais ajouter une
seconde sonde `/model` pour cette donnée.

## Effort et reasoning

Le dashboard conserve cinq niveaux neutres dans les fichiers `.effort` :

| Interface | Niveau TUI |
|---|---|
| `L` | `medium` |
| `M` | `high` |
| `H` | `xhigh` / Extra high |
| `X` | `max` / Max |
| `U` | `ultracode` / Ultra |

La sémantique est commune à Claude Code et Codex, mais la sélection dépend du
moteur. Claude Code reçoit `/effort medium|high|xhigh|max|ultracode`. Codex
utilise le picker `Select Reasoning Level`; `X` et `U` ouvrent
`More reasoning…`, puis choisissent respectivement `Max` ou `Ultra` dans
`Advanced Reasoning`.

Ces cheminements sont des relevés de TUI réels (Claude : hub mx9,
2026-07-28 ; Codex : mx6, codex-cli 0.144.x, 2026-07-28), consignés dans
`scripts/engines.sh`. Comme tout marqueur, ils se contre-relèvent à chaque
montée de version du CLI et ne se devinent jamais. La liste des modèles à
efforts étendus (`X`/`U`) vit dans la couche moteur :
`engines.effort_levels_for_model()` (`scripts/agent-bridge/engines.py`).

Les nouveaux clones livrent `prompts/default.effort` à `M`. Sur un projet
existant, `upgrade.sh` préserve `prompts/` et ne crée ni ne remplace ce fichier :
l'absence reste néanmoins interprétée comme `M` par l'interface et le moteur.

Avant le chargement du prompt agent, Claude reçoit `/model <identifiant>` puis
`/effort <niveau>`. Codex CLI 0.144.4 est piloté par le picker `/model`, qui
sélectionne successivement le modèle puis le niveau de raisonnement : les
arguments directs de `/model` seraient interprétés comme un prompt. Le même
fichier `.effort` est donc réutilisé lors d'un changement de modèle.

Les erreurs TUI qui rendent un agent rouge, leur source et leur traitement sont
documentés dans [ENGINE-ERRORS.md](ENGINE-ERRORS.md).

## Ce qui s'applique à chaud, ce qui exige un redémarrage

C'est le **moteur** qui décide, pas le modèle.

| Changement | Effet |
|---|---|
| Modèle à moteur constant (`claude-*`→`claude-*`, `gpt-*`→`gpt-*`) | appliqué à chaud, automatiquement |
| Effort / raisonnement (`L`…`U`) | appliqué à chaud, automatiquement |
| Moteur (`claude-*` ↔ `gpt-*`) | enregistré seulement — **redémarrage requis** |
| Profil de login | enregistré seulement — **redémarrage requis** |

À moteur constant, le CLI déjà lancé sait changer de modèle et de niveau par
ses propres commandes : la session, la mémoire et l'historique de l'agent sont
préservés, et l'opérateur n'a rien à faire.

Un changement de moteur ou de profil ne peut pas s'appliquer à chaud : le
binaire et la variable d'authentification (`CLAUDE_CONFIG_DIR` / `CODEX_HOME`)
sont fixés au lancement. La nouvelle valeur est écrite dans `.model`/`.login`
et prendra effet au prochain démarrage. **Le framework ne redémarre jamais un
agent de lui-même** : la réponse porte `restart_required: true` et la commande
reste à la main de l'opérateur.

```bash
./scripts/agent.sh restart <id>
```

Dans tous les cas, l'application à chaud n'a lieu que si la session tourne et
que l'agent est libre ; sinon la valeur est conservée et la réponse l'annonce
comme différée (`deferred`) avec sa raison.
