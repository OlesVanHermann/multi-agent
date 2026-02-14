# Chrome Bridge — Guide d'installation et d'utilisation

> Contrôler Chrome depuis Claude Code via une extension Chrome + Native Messaging.
> Remplace `--remote-debugging-port=9222` : même API, Google ne bloque plus le login.

---

## Pourquoi Chrome Bridge

```
AVANT (chrome-shared.py + flag CDP)
  Chrome --remote-debugging-port=9222
    → Google détecte l'automation
    → Login bloqué / vérification supplémentaire
    → Sessions perdues si Chrome redémarre

APRES (chrome-bridge.py + extension)
  Chrome NORMAL + Extension CDP Bridge
    → chrome.debugger API = même puissance que CDP
    → Google ne détecte rien
    → Login fonctionne normalement
```

---

## Architecture

```
┌───────────────┐       ┌──────────────────┐       ┌────────────────────┐
│ Claude Code   │ HTTP  │ Native Host      │ pipes │ Extension Chrome   │
│               │──────►│ (Node.js)        │──────►│ (service worker)   │
│ chrome-       │ :9222 │ cdp-bridge-      │stdin/ │                    │
│ bridge.py     │◄──────│ host.js          │stdout │ chrome.debugger    │
│               │       │                  │◄──────│ chrome.tabs        │
│ AGENT_ID=200  │       │ HTTP server +    │       │ chrome.pageCapture │
│               │       │ native messaging │       │                    │
└───────────────┘       └──────────────────┘       └────────────────────┘
```

**Flux d'une commande :**
1. `AGENT_ID=200 python3 chrome-bridge.py read-text page.txt`
2. HTTP POST `http://localhost:9222/command` → Node.js
3. Node.js écrit sur stdout (pipe Chrome) → `[4 bytes longueur][JSON]`
4. Extension reçoit via `port.onMessage`, exécute `chrome.debugger.sendCommand()`
5. Résultat remonte : extension → Node.js stdin → HTTP response → Python

---

## Prérequis

| Outil | Installation |
|-------|-------------|
| **Node.js** | `brew install node` |
| **Redis** | `docker run -d --name ma-redis-mac -p 127.0.0.1:6379:6379 redis:7-alpine redis-server --appendonly yes` |
| **Docker** | `brew install colima docker && colima start` |
| **Chrome** | Installé normalement (SANS flag `--remote-debugging-port`) |

---

## Installation

### Etape 1 — Charger l'extension dans Chrome

1. Ouvrir `chrome://extensions` dans Chrome
2. Activer **Mode développeur** (toggle en haut à droite)
3. Cliquer **Charger l'extension non empaquetée**
4. Sélectionner le dossier : `/chemin/vers/cdp-bridge/extension/`
5. **Copier l'ID** affiché sous "CDP Bridge" (32 lettres minuscules)

### Etape 2 — Installer le Native Host

```bash
cd /chemin/vers/cdp-bridge
chmod +x install.sh
./install.sh <extension-id>
```

Le script :
- Vérifie que Node.js est installé
- Crée un launcher shell pour le native host
- Génère le manifest native messaging avec l'ID de l'extension
- Installe le manifest dans `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/`

### Etape 3 — Redémarrer Chrome

**Quitter Chrome complètement** (Cmd+Q) puis le rouvrir. Un simple reload ne suffit pas.
L'extension se connecte automatiquement au native host au démarrage.

### Etape 4 — Vérifier

```bash
# Health check
curl http://localhost:9222/health
# → {"status":"ok","extensionConnected":true,...}

# Lister les onglets
curl http://localhost:9222/json
```

### Etape 5 — Copier le script dans le projet

```bash
cp /chemin/vers/cdp-bridge/chrome-bridge.py $BASE/scripts/chrome-bridge.py
chmod +x $BASE/scripts/chrome-bridge.py
```

---

## Utilisation depuis Claude Code

### Principe

Chaque commande est un appel CLI avec `AGENT_ID` en variable d'environnement :

```bash
AGENT_ID=000 python3 $BASE/scripts/chrome-bridge.py <commande> [args]
```

Le `AGENT_ID` permet à chaque agent d'avoir son propre onglet Chrome, stocké dans Redis (`ma:chrome:tab:{agent_id}`).

En session tmux (agents multi-agent), l'AGENT_ID est détecté automatiquement depuis le nom de la session.

### Raccourci

```bash
CHROME="python3 $BASE/scripts/chrome-bridge.py"

$CHROME tab "https://example.com"
$CHROME wait 2
$CHROME read-text page.txt
$CHROME close
```

---

## Commandes

### Navigation

```bash
tab "https://url"          # Créer onglet + naviguer (1 onglet par agent)
goto "https://url"         # Naviguer dans l'onglet existant
reload                     # Rafraîchir
back                       # Page précédente
forward                    # Page suivante
url                        # Afficher URL actuelle
title                      # Afficher titre
```

### Lecture de contenu (PREFERER A SCREENSHOT)

```bash
read output.html           # HTML complet → fichier
read-text output.txt       # Texte seul → fichier (le plus utile pour extraire des données)
read-element "#div" out    # HTML d'un élément → fichier
read-attr "#img" src       # Valeur d'un attribut
read-links                 # Lister tous les liens (texte + href)
eval "document.title"      # Exécuter JavaScript arbitraire
```

**`read-text` est la commande principale pour l'extraction de données.**
Le texte est directement exploitable par l'agent, contrairement aux screenshots.

### Clics

```bash
click "#button"            # Clic par sélecteur CSS
click-text "Accept"        # Clic par texte visible
dblclick "#element"        # Double-clic
hover "#menu"              # Survol
```

### Saisie

```bash
type "#input" "texte"      # Taper dans un champ
fill "#input" "texte"      # Alias de type
clear "#input"             # Vider un champ
press enter                # Touche (enter, tab, escape...)
```

### Formulaires

```bash
select "#country" "France" # Sélectionner dropdown
check "#agree"             # Cocher checkbox
uncheck "#agree"           # Décocher
submit                     # Soumettre formulaire
```

### Scroll

```bash
scroll down                # Scroll bas (500px)
scroll up                  # Scroll haut
scroll bottom              # Aller tout en bas
scroll top                 # Aller tout en haut
scroll-to "#element"       # Scroll vers élément
```

### Attente

```bash
wait 3                     # Attendre N secondes
wait-element "#popup"      # Attendre élément visible
wait-hidden "#loader"      # Attendre élément disparu
wait-text "Success"        # Attendre texte présent
```

### Captures (si le visuel est nécessaire)

```bash
screenshot page.png        # Screenshot viewport
screenshot-full page.png   # Screenshot page entière
pdf output.pdf             # Export PDF
```

### Images

```bash
read-images                # Liste toutes les images (JSON stdout)
read-images images.json    # Sauvegarde liste images en JSON
capture-element "#chart" chart.png  # Capture un élément spécifique
download-images ./images/  # Télécharge toutes les images
```

### Gestion onglets

```bash
get                        # Récupérer mon tabId
close                      # Fermer mon onglet
list                       # Lister tous les mappings agent→tab
status                     # Statut Chrome + bridge
```

---

## Exemples concrets avec Claude Code

### Exemple 1 : Lire un email Gmail et extraire un code

```bash
# Naviguer vers Gmail
AGENT_ID=000 python3 $BASE/scripts/chrome-bridge.py goto "https://mail.google.com/mail/u/0/#search/similarweb"

# Attendre le chargement
AGENT_ID=000 python3 $BASE/scripts/chrome-bridge.py wait 3

# Cliquer sur le premier email
AGENT_ID=000 python3 $BASE/scripts/chrome-bridge.py click-text "Vérification de la connexion"

# Attendre l'ouverture
AGENT_ID=000 python3 $BASE/scripts/chrome-bridge.py wait 3

# Lire le contenu texte de la page
AGENT_ID=000 python3 $BASE/scripts/chrome-bridge.py read-text /tmp/email.txt

# Extraire le code (6 chiffres) depuis le fichier texte
grep -oP '\b[0-9]{6}\b' /tmp/email.txt
```

### Exemple 2 : Crawler un site (agent worker)

```bash
CHROME="AGENT_ID=300 python3 $BASE/scripts/chrome-bridge.py"

# Créer un onglet
$CHROME tab "https://drive.google.com/features"

# Attendre
$CHROME wait 3

# Accepter cookies
$CHROME click-text "Accept" || true

# Lire le contenu texte (pas screenshot)
$CHROME read-text $RESEARCH/drive/google-drive/features.txt

# Lire les liens pour découvrir d'autres pages
$CHROME read-links > $RESEARCH/drive/google-drive/links.txt

# Sauvegarder le HTML complet
$CHROME read $RESEARCH/drive/google-drive/html/features.html

# Fermer l'onglet
$CHROME close
```

### Exemple 3 : Extraire des données SimilarWeb

```bash
CHROME="AGENT_ID=360 python3 $BASE/scripts/chrome-bridge.py"

# Naviguer
$CHROME tab "https://www.similarweb.com/website/example.com/"

# Attendre chargement complet
$CHROME wait 5

# Scroll pour charger le contenu lazy
$CHROME scroll bottom
$CHROME wait 2
$CHROME scroll top

# Lire le texte (trafic, rang, sources)
$CHROME read-text $RESEARCH/seo/similarweb-example.txt

# Extraire les graphiques (canvas/SVG)
$CHROME read-images $RESEARCH/seo/images.json
$CHROME download-images $RESEARCH/seo/images/

# Fermer
$CHROME close
```

---

## Bonne pratique : read-text plutot que screenshot

| Methode | Avantage | Inconvenient |
|---------|----------|-------------|
| **`read-text`** | Donnees exploitables directement, cherchable, parsable | Pas de visuel |
| **`read`** (HTML) | Structure complete, re-parsable | Plus lourd |
| **`screenshot`** | Visuel exact de la page | Non exploitable par l'agent, lourd |

**Regle : toujours preferer `read-text` pour l'extraction de donnees.**
Utiliser `screenshot` uniquement pour le debug visuel ou quand le layout est important.

---

## Codes de sortie

| Code | Signification | Action |
|------|---------------|--------|
| `0` | Succes | Continuer |
| `1` | Erreur generique | Retry possible |
| **`100`** | **Chrome pas lance** | **ARRET IMMEDIAT — signaler a l'utilisateur** |
| `101` | Target obsolete | Auto-cleanup fait |
| `102` | Timeout | Retry 1x |

### Regle critique : Code 100

Si `chrome-bridge.py` retourne code 100 → **NE JAMAIS relancer Chrome automatiquement**.
Les sessions (Gmail, SimilarWeb Pro, Ahrefs Pro, etc.) seraient perdues.

```bash
# INTERDIT
open -a "Google Chrome"

# OBLIGATOIRE
echo "Chrome non actif - intervention manuelle requise"
exit 1
```

---

## Differences avec l'ancien chrome-shared.py

| Aspect | chrome-shared.py (ancien) | chrome-bridge.py (actuel) |
|--------|--------------------------|--------------------------|
| Transport | WebSocket CDP direct | HTTP → Native Messaging → chrome.debugger |
| Chrome requis | `--remote-debugging-port=9222` | Chrome normal + extension |
| Google login | Bloque/detecte | Fonctionne |
| Dependencies Python | `websocket-client` | Aucune (stdlib) |
| Latence | ~5ms/commande | ~20-50ms/commande |
| Barre jaune | Non | Oui (cosmetique, inoffensif) |
| Redis | Supporte | Identique |
| Multi-agent | Supporte | Identique |
| CLI | `tab`, `goto`, `click`... | Identique (drop-in replacement) |

---

## Interdit

```
╔═══════════════════════════════════════════════════════════════╗
║  JAMAIS arreter Chrome (sessions perdues)                     ║
║  JAMAIS relancer Chrome automatiquement                       ║
║  JAMAIS fermer le dernier tab                                 ║
║  JAMAIS lancer un 2eme Chrome                                 ║
║  JAMAIS utiliser Playwright                                   ║
║  JAMAIS utiliser MCP chrome-devtools                          ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## Depannage

### Bridge ne repond pas (`curl: Connection refused`)

1. Chrome est-il ouvert ?
2. Extension active dans `chrome://extensions` ?
3. Recharger l'extension (bouton rafraichir)
4. Si toujours rien : quitter Chrome (Cmd+Q) et rouvrir

### Extension ne se connecte pas au native host

```bash
# Verifier le manifest
cat ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/com.cdpbridge.host.json

# Verifier que l'ID correspond
# L'ID dans "allowed_origins" doit matcher l'ID dans chrome://extensions

# Verifier Node.js
which node

# Verifier les logs extension : chrome://extensions → CDP Bridge → "Inspecter le service worker"
```

### Port 9222 deja utilise

Si Chrome tournait avant avec `--remote-debugging-port=9222` :

```bash
lsof -i :9222
kill <PID>
# Relancer Chrome normalement (SANS le flag)
```

### Redis non disponible

Le mapping agent→tab necessite Redis. Sans Redis, `tab` cree l'onglet mais `screenshot`/`read-text` ne le retrouve pas.

```bash
# Verifier Redis
redis-cli ping

# Lancer Redis (Docker)
docker run -d --name ma-redis-mac -p 127.0.0.1:6379:6379 redis:7-alpine redis-server --appendonly yes
```

---

## Desinstallation

```bash
# Supprimer le native host
cd /chemin/vers/cdp-bridge
./install.sh --uninstall

# Retirer l'extension dans chrome://extensions
```

---

*Chrome Bridge v1.0 — Fevrier 2026*
