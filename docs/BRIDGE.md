# Bridge Agent — Documentation technique

`scripts/agent-bridge/agent.py` est le pont entre Redis et un Claude Code
**interactif tournant dans tmux**. Il n'exécute pas `claude` lui-même : il
suppose qu'une session tmux nommée `{MA_PREFIX}-agent-{id}` existe déjà
(créée par `./scripts/agent.sh start <id>`) et dialogue avec elle via
`tmux send-keys` / `tmux capture-pane`.

```
Redis Streams                    tmux session "{MA_PREFIX}-agent-{id}"
{MA_PREFIX}:agent:{id}:inbox ──► agent.py ──send-keys──► Claude Code (CLI)
{MA_PREFIX}:agent:{id}:outbox ◄─ agent.py ◄─capture-pane─┘
```

```bash
python3 scripts/agent-bridge/agent.py 300
# Prérequis : session tmux "{MA_PREFIX}-agent-300" avec Claude lancé
# (sinon le bridge sort immédiatement avec une erreur)
```

---

## Architecture interne

Quatre threads démons + un serveur health HTTP :

| Thread | Rôle |
|--------|------|
| `redis_listener` | Lit l'inbox Streams via consumer group (XREADGROUP) et alimente la queue |
| `legacy_listener` | Lit l'inbox legacy (List `{MA_PREFIX}:inject:{id}`, BLPOP) — best-effort, sans ack |
| `queue_processor` | Dépile la queue, envoie à Claude (tmux), publie la réponse, XACK |
| `heartbeat` | Publie toutes les 10 s sur `mi:agent:{id}:heartbeat` + `pane_state` (B6) |
| `health_server` | HTTP `GET /health` sur `127.0.0.1:{AGENT_HEALTH_PORT_BASE + id}` (token `HEALTH_TOKEN` requis) |

Le thread principal (`run()`) lit stdin : lignes normales = prompts locaux,
lignes `/commande` = commandes interactives. **EOF sur stdin arrête le bridge.**

### Consumer groups (A4)

L'inbox est consommée via le groupe `bridge` (consumer `agent-{id}`), créé
de façon idempotente avec `id='$'` et `mkstream=True` :

- Au démarrage, les messages **lus mais non acquittés** lors d'un run
  précédent (crash) sont rejoués d'abord (lecture avec id `'0'`), puis les
  nouveaux messages sont consommés (id `'>'`).
- Un prompt n'est **XACK qu'après publication de la réponse** dans l'outbox :
  un crash en cours de traitement ⇒ rejeu au redémarrage, pas de perte.
- Les messages de type `response` / `reload_prompt` (et entrées inconnues ou
  élaguées) sont acquittés immédiatement.
- L'inbox legacy (List) reste destructive (BLPOP) : préférer les Streams.

### Bornage des streams (A3)

Tous les `XADD` métier (inbox/outbox) sont bornés à `IO_STREAM_MAXLEN`
(défaut 10000, `approximate=True`) ; les streams monitoring à 1000.
Un lint de test (`tests/test_stream_bounds.py`) vérifie qu'aucun `xadd`
sans `maxlen` n'est introduit.

---

## Détection de fin de réponse (A1 / E1)

Le bridge ne lit pas un flux structuré : il **parse le rendu du terminal**
(`tmux capture-pane -S -200`). Tous les marqueurs UI sont externalisés dans
`scripts/agent-bridge/markers.<moteur>.yaml` — si un libellé du CLI change,
c'est ce fichier qu'on corrige, pas le code.

**E1 — un fichier de marqueurs par moteur.** Le moteur du bridge est choisi par
la variable d'environnement `AGENT_CLI`, posée par `agent.sh` / `infra.sh`
après inférence depuis le modèle effectif (`claude-*` ou `gpt-*`) :

| `AGENT_CLI` | Fichier chargé |
|---|---|
| absent / `claude` (défaut) | `markers.claude.yaml` |
| `codex` | `markers.codex.yaml` |

`markers.yaml` est un lien symbolique vers `markers.claude.yaml`
(rétro-compatibilité). Le chargement et la validation passent par
`engines.load_markers()`, qui **échoue immédiatement** si un marqueur porte
encore le sentinelle `__A_RENSEIGNER__` : des marqueurs devinés casseraient la
détection busy/ready **sans aucune erreur visible**. Voir
[ENGINES.md](ENGINES.md).

Logique de `_wait_for_response` :

1. Capture une baseline du pane avant la réponse.
2. Boucle de scrutation **adaptative** (A2) : intervalle `POLL_MIN` tant que
   le pane change, allongé ×1.5 jusqu'à `POLL_MAX` dès stabilité.
3. La réponse est considérée terminée quand la zone de prompt (3 dernières
   lignes non vides) contient la ligne de statut (`status_line`), qu'un
   marqueur de prompt (`prompt_markers` : `❯`, `>`, …) est visible, et que
   cette zone est stable depuis `STABLE_READY_SECS` (fallback sans marqueur :
   `STABLE_FALLBACK_SECS` ; mode plan : `STABLE_PLAN_SECS`).

### Cas particuliers gérés pendant l'attente

| Détection (markers.<moteur>.yaml) | Réaction du bridge |
|--------------------------|--------------------|
| `Conversation compacted` (nouvelle occurrence) | Re-met en queue : msg 1 `deviens agent <prompt>` (ré-injection identité) + msg 2 rappel du contexte (dernière ligne `.history` + prompt d'origine), qui porte l'`ack_id` et le `correlation_id` d'origine. Statut transitoire `context_compacted`. |
| `API Error:` / `rate_limit` / `overloaded_error`… (`api_error_patterns`) | Re-queue du prompt avec backoff `RETRY_BACKOFF_SECS` (max 2 retries). Événement `api_error_retry` dans `events.jsonl`, statut transitoire `api_error_retry`. |
| `How is Claude doing` (sondage de session) | Auto-rejet : envoi de `0`, puis reprise de l'attente. |
| `Would you like to proceed` (plan mode) | Statut Redis `waiting_approval` tant que la demande est visible ; l'utilisateur approuve directement dans le pane tmux. |
| `Press up to edit queued messages` | Le prompt n'a pas été traité (Claude occupé) : retour immédiat. |

*(Les libellés ci-dessus sont ceux du moteur `claude`. Pour un autre moteur, ce
sont les valeurs de son propre `markers.<moteur>.yaml`.)*

### Une seule implémentation du parsing de pane (E1)

Trois composants déduisent l'état d'un agent depuis son pane : le bridge
(`agent.py`), le dashboard (`cache.py`) et l'outil de diagnostic
(`debug-color.py`). Les deux derniers portaient une **copie manuelle** du même
parsing, en bash, avec les chaînes d'UI en dur — et ces copies avaient dérivé.

Le corps du parsing est désormais **généré** depuis les marqueurs :

```python
engines.build_pane_eval(markers)              # $out, $pane_cmd → 14 champs
engines.build_pane_scan(markers, MA_PREFIX)   # + capture tmux, 1 fork pour N agents
```

`tests/test_pane_scan.py` exécute le bash généré **et** `_parse_pane_state()` sur
17 panes réels × 3 process, et compare les 14 champs un à un. Toute divergence
future casse le test.

Le scan tmux du dashboard n'est qu'un **repli** (quand le `pane_state` publié par
le bridge est absent ou périmé dans Redis). Un agent dont les marqueurs ne sont
pas relevés y est **ignoré** : son état viendra de Redis. Un état absent est
rafraîchi ; un état faux est simplement affiché.

---

## Format des messages

### Envoyer un prompt (inbox)

```bash
./scripts/send.sh 300 "Analyse le README"
# ou
redis-cli XADD "A:agent:300:inbox" MAXLEN '~' 10000 '*' \
  prompt "Analyse le README" from_agent "cli" \
  correlation_id "$(uuidgen)" timestamp "$(date +%s)"
```

Champs : `prompt` (requis), `from_agent`, `correlation_id` (F2, optionnel),
`timestamp`. Un `from_agent` invalide (ni ID d'agent ni valeur réservée
`cli|manual|legacy|auto_init|…`) est remplacé par `unknown`.

### Réponse (outbox)

```
{MA_PREFIX}:agent:{id}:outbox
  response, from_agent, to_agent, timestamp, chars
  correlation_id   # F2 : écho du correlation_id de la requête
```

Si `from_agent` est un autre agent **vivant** (session tmux active), la
réponse lui est aussi routée dans son inbox (type `response`, découpée en
chunks de 15000 caractères si nécessaire, champ `complete`). Les expéditeurs
`cli`, `manual`, `auto_init`, etc. ne reçoivent pas de routage retour.

### Autres types inbox

- `type=response` : notification `[FROM xxx]…[/xxx]` injectée comme prompt.
- `type=reload_prompt` : ré-injection du prompt agent (après compaction).

---

## Auto-chargement du prompt agent

Au démarrage, le bridge cherche le prompt de l'agent dans `prompts/` :

- Pipeline standard : `prompts/{id}-*.md` → envoie `deviens agent <chemin>` ;
- x45 : répertoire `prompts/{id}*/` avec `system.md` + `memory.md` +
  `methodology.md` → envoie la liste des fichiers à lire ;
- puis, si `{id}.history` existe, un rappel de la dernière entrée.

Chaque prompt traité est ajouté à `prompts/…/{id}.history` (horodaté).

---

## Commandes interactives (stdin)

```
/status            État + taille de queue + tâches accomplies
/queue             Taille de la queue
/send <id> <msg>   Envoyer à un autre agent (broadcast : /send all <msg>)
/help              Aide
```

Toute autre ligne stdin est traitée comme un prompt local (`from_agent=manual`).

---

## Variables d'environnement

| Variable | Défaut | Rôle |
|----------|--------|------|
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` | `localhost` / `6379` / vide | Connexion Redis |
| `MA_PREFIX` | `A` | Préfixe des clés métier (`A:agent:300:inbox`…) |
| `MONITORING_PREFIX` | `mi` | Préfixe des streams monitoring |
| `LOG_DIR` | `logs/` | Logs : `{LOG_DIR}/{id}/bridge_{ts}.log` + `events.jsonl` |
| `RESPONSE_TIMEOUT` | `300` | Attente max d'une réponse (s) |
| `POLL_MIN` / `POLL_MAX` | `0.2` / `2.0` | Scrutation adaptative du pane (A2) |
| `STABLE_READY_SECS` | `5` | Stabilité requise avec marqueur de prompt |
| `STABLE_FALLBACK_SECS` | `10` | Stabilité requise sans marqueur |
| `STABLE_PLAN_SECS` | `15` | Stabilité requise en mode plan |
| `RETRY_BACKOFF_SECS` | `10` | Backoff entre retries après erreur API |
| `IO_STREAM_MAXLEN` | `10000` | Borne des streams inbox/outbox (A3) |
| `AGENT_HEALTH_PORT_BASE` | `9100` | Port health = base + id numérique |
| `HEALTH_TOKEN` | vide | Token du endpoint `/health` (vide = tout refusé) |
| `VERIFY_MAX_RETRIES` | `3` | V3 : budget de retries verify par tâche |
| `VERIFY_TIMEOUT` | `600` | V3 : timeout (s) d'un `verify_cmd` |
| `PROJECT_DIR` | `$BASE/project` | V3 : cwd du verify + règles anti-hacking |
| `WAL_MAXLEN` | `100000` | V3 : borne du stream `{MA_PREFIX}:wal` |
| `WATCHDOG_STALL_THRESHOLD` | `600` | V3 : silence WAL (s) avant nudge watchdog |

Boucle verify, WAL et détection de stall : voir `docs/V3.md`.

---

## Keepalive des logins (crontab-scheduler)

Le scheduler (`scripts/crontab-scheduler.py`, session tmux
`{MA_PREFIX}-agent-001`) balaie tous les profils `login/claude*` :

- **Sweep** toutes les `MA_KEEPALIVE_SWEEP_MIN` minutes (défaut `720` = 12 h,
  `0` = désactivé) : pour chaque profil, démarre (ou réutilise) la session
  tmux `{MA_PREFIX}-agent-002-{profil}`, envoie un « hello » (vrai appel API
  → la session OAuth ne s'endort pas), scrape `/status` (usage + identité)
  et écrit `keepalive/usage_{profil}.json`, `info_{profil}.json` et un
  récapitulatif `keepalive/sweep_report.json`.
- **États** par profil : `ok`, `no_bars`, `login_required` (re-login à
  faire), `timeout`. Visible dans le panneau « Login Keep Alive » du
  dashboard et dans `logs/crontab-scheduler.log`.
- Le sweep est horodaté (`keepalive/last_sweep.txt`), pas aligné sur
  l'horloge : au (re)démarrage, si le dernier sweep date de plus de 12 h,
  il part immédiatement.
- `{profil}.suspended` dans `keepalive/` exclut un profil du sweep ;
  `LOGIN_DIR` change le répertoire des profils.
- L'ancien round-robin `/status` (10 min) est désactivé par défaut ;
  `MA_KEEPALIVE_RR_MIN=10` le réactive.

---

## Monitoring

- **Heartbeat** : `mi:agent:{id}:heartbeat` toutes les 10 s (statut, mémoire,
  CPU via psutil, compteurs de messages), borné à 1000 entrées.
- **État dashboard (B6)** : le bridge dérive l'état du pane (`pane_state`)
  et le publie dans le hash `{MA_PREFIX}:agent:{id}` — le dashboard lit
  Redis, sans re-scanner tmux.
- **Statuts** dans `{MA_PREFIX}:agent:{id}` (`status`) : `idle`, `busy`,
  `waiting_approval`, `api_error_retry`, `context_compacted`, `has_bashes`,
  `stopped`.
- **Health HTTP** : `GET http://127.0.0.1:{base+id}/health?token=…` →
  `status`, `agent_id`, `uptime_seconds`, `last_heartbeat_ts`,
  `redis_connected`, `pty_active`.
- **Healthcheck global** : `python3 scripts/agent-bridge/healthcheck.py`.

---

## Tests

- `tests/test_e2e_bridge.py` (G1) : chaîne complète Redis → agent.py → tmux
  avec un faux Claude (`tests/fixtures/fake_claude.sh`) — nominal,
  compaction, erreur API, sondage, plan mode. Skippés si `tmux` ou
  `redis-server` manquent ; exécutés en CI (`.github/workflows/e2e.yml`).
- `tests/test_consumer_groups.py` (A4/G2) : routage inbox, ack après
  publication, reprise après crash sur un vrai Redis.
- `tests/test_stream_bounds.py` (A3), `tests/test_markers_externalized.py` (A1),
  `tests/test_adaptive_poll.py` (A2).

```bash
python3 -m pytest tests/test_e2e_bridge.py -v
```
