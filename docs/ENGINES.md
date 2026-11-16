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

Les fichiers `.effort` portent cinq niveaux dont les lettres suivent les noms
réels des CLI (décision opérateur, 2026-10-09) :

| Interface (bouton) | Fichier | Claude Code | Codex |
|---|---|---|---|
| `L` | `L` | `/effort low` | `1. Low` |
| `M` | `M` | `/effort medium` | `2. Medium` |
| `H` | `H` | `/effort high` | `3. High` |
| `X` | `X` | `/effort xhigh` | `4. Extra high` |
| `M` (max, bulle « max ») | `MAX` | `/effort max` | `5. More reasoning…` → `1. Max` |

`Ultra` (codex) n'est jamais proposé. **Ultracode** n'est plus un niveau : c'est
un interrupteur séparé, propre aux modèles Claude 5 (`prompts/<id>.ultracode`
= `on` | `off`, bouton `U` du panneau). Claude Code le traite comme un état de
SESSION indépendant du niveau : `/effort <niveau>` ne le change jamais et il
n'est jamais persisté. Le framework envoie donc `/effort ultracode on|off`
à chaud et le renvoie à chaque démarrage quand il vaut `on`
(`engine_apply_ultracode`). Le bridge lit son état réel sur la bordure du
composer (`runtime_ultracode_pattern`).

Jusqu'au 2026-10-09, les lettres valaient `L`=medium, `M`=high, `H`=xhigh,
`X`=max, `U`=ultracode. `patch/migrate-effort-letters.py` (appelé par
`upgrade.sh`, idempotent, témoin `prompts/.effort-letters-v2`, originaux dans
`removed/`) convertit `L→M`, `M→H`, `H→X`, `X→MAX` et `U→MAX` + `.ultracode on`,
sans changer le niveau réel d'aucun agent.

Ces cheminements sont des relevés de TUI réels (Claude : hub mx9, 2026-07-28,
Claude Code 2.1.295 sur mx3, 2026-10-09 ; Codex : mx6, codex-cli 0.144.x,
2026-07-28, 0.160.1 sur mx3, 2026-10-09), consignés dans `scripts/engines.sh`.
Comme tout marqueur, ils se contre-relèvent à chaque montée de version du CLI
et ne se devinent jamais. La liste des modèles à efforts étendus (`X`/`MAX`)
et à Ultracode vit dans la couche moteur : `engines.effort_levels_for_model()`
et `engines.ultracode_supported()` (`scripts/agent-bridge/engines.py`).

L'absence de `prompts/default.effort` est interprétée comme `H` (high) par
l'interface et le moteur.

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

## Mettre à jour le CLI sans perdre la session (`update`)

Une nouvelle version de Claude Code ou de Codex ne sert qu'au prochain
lancement du binaire. `restart` le relance, mais dans une **nouvelle**
conversation. `update` relance le même CLI **sur sa conversation** :

```bash
./scripts/agent.sh update 300-300          # bouton « update harness » du terminal
```

**Avant de toucher au CLI** (sinon refus sans effet, HTTP 409, jamais forcé) :

| Contrôle | Refus si | Code |
|---|---|---|
| Au repos | bridge `busy`/`retrying`, ou pane : tour en cours, question ou menu (`waiting_select`, `approval`), plan mode, commande en fond, compaction, messages en file, login expiré, erreur | 3 `not_idle` |
| Bridge | n'annonce pas `cli_hold` dans `bridge_caps` → `reload-bridge` d'abord | 4 `bridge_reload` |
| Profil | le process tourne sur un autre profil (ou moteur) que la configuration → `restart` | 5 `restart_required` |

« Au repos » est la même lecture du pane que la couleur du dashboard
(`engines.build_pane_scan`) ; elle est refaite 2 s après la pose du verrou.
Le profil en cours est lu dans l'environnement du process au premier plan
(`CLAUDE_CONFIG_DIR` / `CODEX_HOME`) : la session vit dans CE répertoire.

**Commandes, par moteur** (tmux `send-keys` sur `agent-<id>:0`) :

| Étape | Claude Code | Codex |
|---|---|---|
| Sortie | `C-u`, `/exit`, Entrée | `C-u`, `/exit`, Entrée |
| Ligne imprimée | `claude … --resume <id>` | `codex resume <id>` |
| Reprise | `CLAUDE_CONFIG_DIR=<base>/login/claudeXY claude --dangerously-skip-permissions --resume <id>` | `env -u OPENAI_API_KEY -u CODEX_API_KEY TMPDIR=/tmp/codex-<agent> CODEX_HOME=<base>/login/codexXY sh -c 'mkdir -p "$TMPDIR" && exec "$0" "$@"' codex resume <id> --dangerously-bypass-approvals-and-sandbox -c forced_login_method=chatgpt` |
| Prêt | `❯` ou `Try "` | `OpenAI Codex (v` ou `› `, sans « Resuming session » |

Puis `/model`, effort, advisor et ultracode, comme au démarrage.

1. Le bridge reçoit un verrou `agent:<id>:cli_hold` (TTL 600 s) et retient ses
   livraisons : pendant la relance, le pane 0 est un shell, et un prompt collé
   là serait exécuté comme une commande.
2. Sortie par la commande du CLI (`exit_command` des marqueurs, `/exit`),
   une seule frappe ; sans sortie en 10 s, échec et CLI intact. Jamais
   Ctrl-C : la double frappe ne quittait pas Claude Code 2.1.296 / 2.1.322
   (mx6, 2026-11-13).
3. Le CLI imprime sa commande de reprise. L'identifiant est lu avec
   `resume_hint_pattern` (marqueurs du moteur), sur une capture `-J`.
4. Relance du même profil avec reprise : `claude … --resume <id>`,
   `codex resume <id> …`. Puis modèle, effort, advisor et ultracode, comme au
   démarrage. La fenêtre bridge n'est pas relancée : pas de nouvel auto-init.

Si la sortie n'imprime aucun identifiant **nouveau** (session sans message,
libellé du CLI changé) ou si la reprise ne démarre pas, `update` se replie sur
un redémarrage complet et le signale (`UPDATE_RESULT … mode=restarted`).
Un identifiant déjà présent dans le scrollback n'est jamais réutilisé.
Après une reprise réussie, `update` réécrit aussi `<id>.session` (section
suivante).

## Repartir sur une nouvelle session (`new-session`)

Le contraire d'`update` : on **abandonne** la conversation en cours.

```bash
./scripts/agent.sh new-session 300-300     # bouton « new session » du terminal
```

Mêmes gardes qu'`update` : refus sans effet si l'agent n'est pas au repos
(code 3) ou si son bridge ne sait pas patienter (code 4). Puis `/exit` du CLI
qui tourne, arrêt sans sauvegarde et démarrage `--fresh` : l'ancien
`<id>.session` part dans `removed/`, la nouvelle session reçoit modèle, effort,
advisor et ultracode, son identifiant est relevé au démarrage (`/status`) et le
bridge relancé envoie « deviens agent ». Le moteur quitté est celui qui tourne,
le nouveau suit la configuration. Résultat : `UPDATE_RESULT … mode=new
session=<uuid>`. `000` est refusé (code 6) : `infra.sh start --fresh`.
L'identifiant complet (`322-222`) ne renouvelle que cet agent ; un identifiant
de triangle nu (`322`) renouvelle chacun de ses membres.

## Retrouver sa session après un arrêt (`stop` → `start`)

`stop` sauvegarde la session du CLI ; `start` la reprend. Même mécanique que
`update` (sortie par la commande du CLI, identifiant imprimé, reprise), mais
séparée dans le temps par un fichier d'état :

```text
prompts/<dir-agent>/<id>.session      # mode 600, ignoré par git, jamais envoyé au hub
claude3a                              # profil EFFECTIF du process
claude                                # moteur
2c2302bd-c230-428d-acaf-6395c68188e2  # identifiant de session
```

Le fichier vit dans le répertoire de l'agent (celui de son `.md` /
`.history`), sinon dans `prompts/` pour un agent à plat. Il est lu à ce chemin
exact, **jamais en cascade** comme `.model` / `.login` : un satellite `300-100`
ne reprend jamais la session de `300`.

**Arrêt** (`stop <id>`, `stop all` en parallèle, bouton stop, `infra.sh stop`
pour 000) — jamais bloquant :

| Situation | Effet |
|---|---|
| Au repos (même contrôle que `update`) | bridge arrêté, `/exit`, identifiant lu, fichier écrit, session tmux fermée |
| Occupé, question, menu, profil illisible, CLI qui ne quitte pas, aucun identifiant | arrêt comme avant, **sans** sauvegarde ; un fichier existant n'est pas touché |

Le profil écrit est celui du process (`CLAUDE_CONFIG_DIR` / `CODEX_HOME`), pas
celui de la configuration : la conversation vit dans CE profil.

**Relevé au démarrage** (sécurité en plus de l'arrêt) : `start`, `start all`,
`restart` et `infra.sh start` lisent l'identifiant de la session en cours par
la commande de statut du CLI (`status_command`, `status_session_pattern`,
`status_dismiss_key` des marqueurs) et écrivent aussitôt `<id>.session`, avant
le lancement du bridge. Un arrêt sans sauvegarde (agent occupé, commandes en
fond, CLI qui ne quitte pas) laisse donc un fichier qui pointe la conversation
en cours : le `start` suivant la reprend. Jamais bloquant : un statut illisible
est signalé et le démarrage continue.

| Moteur | Commande | Ligne lue | Fermeture |
|---|---|---|---|
| claude | `/status` (panneau Settings/Status) | `Session ID:        <uuid>` | Échap |
| codex | `/status` (fiche dans le transcript) | `Session:             <uuid>` (pas l'UUID du workspace ChatGPT) | — |

Relevés sur TUI réels (mx81, 2026-11-16 : Claude Code 2.1.325, codex-cli
0.169.0) : même identifiant que celui imprimé par `/exit`, et après reprise.
Une session Codex sans aucun échange n'est pas persistée : sa reprise échoue
et retombe sur une nouvelle session. Banc d'essai sur CLI réels, en tmux
isolé : `MA_REAL_CLI_BENCH=1 python3 -m pytest tests/test_session_id_real_cli.py`.

**Démarrage** (`start <id>`, `start all`, `restart`, watchdog, `infra.sh start`
pour 000) :

| Situation | Effet |
|---|---|
| Profil et moteur configurés = ceux du fichier, UUID valide | `claude … --resume <id>` / `codex resume <id> …`, puis modèle, effort, advisor, ultracode ; bridge lancé avec `AGENT_RESUMED=1` : **« deviens agent » rejoué, sans « Continue. »** (qui ferait refaire la dernière tâche) — l'agent recharge son identité et un prompt modifié, même si la conversation reprise n'avait jamais été amorcée |
| Profil ou moteur changé, fichier illisible | nouvelle session, fichier archivé dans `removed/` |
| `--fresh` (`start`, `restart`, `infra.sh start`) | nouvelle session, fichier archivé dans `removed/` |
| La reprise ne démarre pas (CLI sorti : session introuvable dans le profil) | nouvelle session, fichier archivé dans `removed/` |

Une reprise garde l'identifiant (vérifié sur TUI réels mx5, 2026-11-13 :
Claude Code et codex-cli impriment le même identifiant à la sortie suivante, et
la session reprise se souvient de l'échange précédent). Le fichier gardé après
une reprise pointe donc toujours la session en cours : un arrêt sans
sauvegarde (agent occupé, crash relancé par le watchdog) la reprend quand même.
Sur un identifiant inconnu, les deux CLI sortent en 1 à 2 s (`No conversation
found with session ID` / `No saved session found with ID`) : le repli est
immédiat.

Dans tous les cas, nouvelle session comme session reprise, le démarrage rejoue
le réglage du CLI (modèle, effort, advisor, ultracode) puis « deviens agent ».
Constat mx81 (2026-11-14) : le watchdog relançait un agent pendant sa
configuration, avant tout auto-init ; la conversation sauvegardée par cet arrêt
était reprise sans « deviens agent », et l'agent tournait sans son rôle.

**Watchdog pendant le démarrage** : `start` (et `infra.sh start` pour 000)
pose `desired_state=starting` + `starting_at` sur `agent:<id>`. Le bridge — et
donc `/health` — n'existe qu'en fin de lancement : tant que le marqueur est en
place, le watchdog ne compte aucun échec, dans la limite de
`WATCHDOG_STARTUP_GRACE_S` (180 s par défaut), puis le lève au premier
`/health` sain (jamais s'il est devenu `stopped` entre-temps).
