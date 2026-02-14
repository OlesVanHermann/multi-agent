INTERDICTION D'HALUCINER
OBLIGATION d'OBEIR AUX PROMPTS. NE JAMAIS SORTIR DU CADRE DEFINIS PAR LE PROMPT
APPRENTISSAGE: Quand je suis guidé par un humain et que je reçois des instructions AUTRES que "go <entreprise>", c'est du nouveau savoir. Je DOIS mettre à jour mon prompt avec ces nouvelles expériences pour être autonome la prochaine fois.

# Configuration des Chemins

## Variables

Tous les prompts utilisent ces variables. Elles sont définies dans `project-config.md` à la racine.

| Variable | Description | Défaut |
|----------|-------------|--------|
| `$BASE` | Racine multi-agent | `/chemin/vers/multi-agent` |
| `$POOL` | Pool requests | `$BASE/pool-requests` |
| `$PROJECT` | Projet cible (code source) | `$BASE/project` |
| `$LOGS` | Logs des agents | `$BASE/logs` |
| `$PROMPTS` | Prompts des agents | `$BASE/prompts` |
| `$REMOVED` | Corbeille sécurisée | `$BASE/removed` |

---

## Chemins dérivés

| Usage | Chemin |
|-------|--------|
| PR pending | `$POOL/pending/` |
| PR assigned | `$POOL/assigned/` |
| PR done | `$POOL/done/` |
| Specs | `$POOL/specs/` |
| Tests manifests | `$POOL/tests/` |
| Knowledge/Inventory | `$POOL/knowledge/` |
| State | `$POOL/state/` |
| Sessions | `$BASE/sessions/` |
| Agent logs | `$LOGS/{agent_id}/` |

---

## Dans les prompts

Remplacer les chemins hardcodés par les variables :

```bash
# AVANT (hardcodé)
cat /Users/claude/projet-new/pool-requests/pending/PR-DOC-*.md

# APRÈS (variable)
cat $POOL/pending/PR-DOC-*.md
```

---

## Initialisation

Au démarrage, l'agent 000 (Architect) :

1. Lit `$BASE/project-config.md`
2. Exporte les variables :
   ```bash
   export BASE="/chemin/vers/multi-agent"
   export POOL="$BASE/pool-requests"
   export PROJECT="$BASE/project"
   export LOGS="$BASE/logs"
   ```
3. Les agents héritent de ces variables via leur environnement

---

## Configuration projet

Créer `$BASE/project-config.md` :

```markdown
# Configuration Projet

## Chemins
BASE=/Users/xxx/multi-agent
POOL=$BASE/pool-requests
PROJECT=$BASE/project
LOGS=$BASE/logs

## Projet
PROJECT_NAME=mon-projet
PROJECT_REPO=https://github.com/xxx/mon-projet

## Agents Dev (3XX)
AGENTS_DEV=300,301,302
AGENT_300_NAME=backend
AGENT_301_NAME=frontend
AGENT_302_NAME=api

## API Doc (optionnel)
API_DOC_PATH=$PROJECT/docs/api
```

---

## Chrome Partagé

**UN SEUL Chrome pour tous les agents, chacun avec son propre onglet.**

### Configuration

| Paramètre | Valeur |
|-----------|--------|
| **Port** | 9222 |
| **Profile** | ~/.chrome-multi-agent |
| **Script** | $BASE/scripts/chrome.sh |
| **Mapping Redis** | ma:chrome:tab:{agent_id} |

### Lancer Chrome

```bash
# Vérifier / Lancer
$BASE/scripts/chrome.sh status
$BASE/scripts/chrome.sh start
$BASE/scripts/chrome.sh stop
```

### Utilisation par les agents

```bash
# 1. Créer son onglet
TAB_ID=$(python3 $BASE/scripts/chrome-bridge.py tab $AGENT_ID "$URL_CIBLE")

# 2. Récupérer son tabId (stocké dans Redis)
TAB_ID=$(python3 $BASE/scripts/chrome-bridge.py get $AGENT_ID)

# 3. Interagir via CDP WebSocket
# ws://127.0.0.1:9222/devtools/page/$TAB_ID

# 4. Fermer son onglet
python3 $BASE/scripts/chrome-bridge.py close $AGENT_ID
```

### Connexion CDP (Python)

```python
import json
import websocket

TAB_ID = "..."  # Récupéré via chrome-bridge.py get
WS_URL = f"ws://127.0.0.1:9222/devtools/page/{TAB_ID}"

ws = websocket.create_connection(WS_URL)

# Naviguer
ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": "https://example.com"}}))
result = json.loads(ws.recv())

# Exécuter JavaScript
ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {"expression": "document.title", "returnByValue": True}}))
result = json.loads(ws.recv())

# Screenshot
ws.send(json.dumps({"id": 3, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
result = json.loads(ws.recv())
# result['result']['data'] = image base64

ws.close()
```

### Agents utilisant Chrome

| Agent | Site | Usage |
|-------|------|-------|
| 330 | Trustpilot | Réputation |
| 331 | Reddit | Réputation |
| 332 | WebHostingTalk | Réputation |
| 333 | G2 | Réputation |
| 334 | YouTube | Réputation |
| 335 | Forums | Réputation |
| 340 | PageSpeed | Performance |
| 341 | Latence | Performance |
| 344 | Pricing | Performance |
| 345 | BuiltWith | Infrastructure |
| 350 | Support | Entreprise |
| 351 | LinkedIn Jobs | Entreprise |
| 352 | LinkedIn | Key People |
| 353 | LinkedIn | Company |
| 355 | X.com | Social |
| 356 | News | Presse |
| 357 | Mastodon | Social |
| 360 | SimilarWeb | SEO complet |
| 364 | Ahrefs | SEO complet |
| 368 | Ubersuggest | SEO complet |
| 373 | Google SEO + Ads | SERP + PageSpeed + Ads |

### Agents d'agrégation (sans Chrome)

| Agent | Entrées | Sortie |
|-------|---------|--------|
| 323 | 320, 321, 322 | 323/seo_technique.json, 323/seo_technique.md |
| 336 | 330-335 | 336/reputation.json, 336/reputation.md |
| 347 | 340-346 | 347/performance.json, 347/performance.md |
| 354 | 350-357 | 354/entreprise.json, 354/entreprise.md |
| 374 | 360,364,368,373 | 374/seo.json, 374/seo.md |

### Agents de monitoring (exécution séparée)

| Agent | Fréquence | Entrées | Sortie |
|-------|-----------|---------|--------|
| 348 | Hebdo | 344/pricing.json | 348/changes.json, 348/notifications.json |
| 349 | Hebdo | 343/ptr_snapshot*.json | 349/ptr_analysis.json, 349/ptr_report.md |

### Règle critique

```
╔═══════════════════════════════════════════════════════════════╗
║  UN SEUL Chrome partagé sur port 9222                         ║
║                                                               ║
║  ✗ INTERDIT : Lancer un autre Chrome                          ║
║  ✗ INTERDIT : pkill Chrome, killall Chrome                    ║
║                                                               ║
║  ✓ Vérifier: $BASE/scripts/chrome.sh status                 ║
║  ✓ Lancer si absent: $BASE/scripts/chrome.sh start          ║
║  ✓ Chaque agent crée SON onglet via chrome-bridge.py          ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## Communication Redis (Bridge)

**Format actuel : Redis Streams** (pas Lists)

### Envoyer un message à un agent

```bash
# Fonction helper
send_to_agent() {
    TO=$1
    MSG=$2
    FROM=${3:-$(basename $0 .md | cut -d'-' -f1)}
    redis-cli XADD "ma:agent:${TO}:inbox" '*' \
        prompt "$MSG" \
        from_agent "$FROM" \
        timestamp "$(date +%s)" > /dev/null
}

# Exemples
send_to_agent 100 "301 done scaleway.com"
send_to_agent 302 "go scaleway.com" 100
```

### Ou directement

```bash
redis-cli XADD "ma:agent:100:inbox" '*' prompt "301 done scaleway.com" from_agent "301" timestamp "$(date +%s)"
```

### Script officiel

```bash
/Users/claude/multi-agent/scripts/send.sh FROM TO "message"
/Users/claude/multi-agent/scripts/send.sh 301 100 "301 done scaleway.com"
```

### ANCIEN format (OBSOLETE - ne plus utiliser)

```bash
# NE PLUS UTILISER
redis-cli RPUSH "ma:inject:100" "message"
```

---

---

## Règle de sécurité : JAMAIS de suppression

**INTERDIT dans tous les prompts et scripts :**
- `rm -rf`
- `rm -r`
- `rm`
- `rmdir`
- `unlink`

**OBLIGATOIRE : Utiliser mv vers $REMOVED/**

```bash
# MAUVAIS - INTERDIT
rm -rf $STUDY_DIR/300/TODO/

# BON - Déplacer vers removed/
mv "$target" "$REMOVED/$(date +%Y%m%d_%H%M%S)_$(basename $target)"
```

### Fonction safe_rm

```bash
safe_rm() {
    local target="$1"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local name=$(basename "$target")
    mkdir -p "$REMOVED"
    mv "$target" "$REMOVED/${timestamp}_${name}"
    echo "Moved to: $REMOVED/${timestamp}_${name}"
}

# Usage
safe_rm /chemin/vers/fichier
safe_rm /chemin/vers/dossier
```

---

*Voir `examples/` pour des exemples concrets.*
