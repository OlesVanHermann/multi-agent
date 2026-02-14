# CDP Bridge — Chrome Extension

> Remplace `--remote-debugging-port=9222` par une extension Chrome.  
> Même API, mêmes commandes, mais Google ne bloque plus le login.

## Le Problème

```
Chrome + --remote-debugging-port=9222
  → Google détecte l'automation
  → Login bloqué / verification supplémentaire
```

## La Solution

```
Chrome NORMAL + Extension CDP Bridge
  → chrome.debugger API = même puissance que CDP
  → Google ne détecte rien
  → Login fonctionne normalement
```

## Architecture

```
┌─────────────────────┐          ┌────────────────────┐          ┌──────────────────────┐
│  chrome-bridge.py   │  HTTP    │  Native Host       │  pipes   │  Extension Chrome    │
│  (drop-in replace   │ ◄──────► │  (Node.js)         │ ◄──────► │  (service worker)    │
│   chrome-shared.py) │ :9222    │  cdp-bridge-host.js│ stdin/   │                      │
│                     │          │                    │ stdout   │  chrome.debugger     │
│  Même CLI:          │          │  Endpoints:        │          │  chrome.tabs         │
│  tab, goto, click,  │          │  /json             │          │  chrome.pageCapture  │
│  screenshot, etc.   │          │  /command           │          │                      │
└─────────────────────┘          └────────────────────┘          └──────────────────────┘
```

### Flux d'une commande

```
1. python3 chrome-bridge.py screenshot out.png
2. → HTTP POST http://localhost:9222/command
     {"action": "screenshot", "params": {"tabId": 42}}
3. → Node.js écrit sur stdout (pipe vers Chrome)
     [4 bytes longueur][JSON]
4. → Chrome lit le pipe, déclenche port.onMessage dans le service worker
5. → Extension exécute chrome.debugger.sendCommand("Page.captureScreenshot")
6. → Résultat remonte : extension → port.postMessage → stdout → Node.js stdin
7. → Node.js renvoie la réponse HTTP à Python
8. → Python décode le base64, écrit out.png
```

## Installation (macOS)

### Étape 1 — Charger l'extension dans Chrome

1. Ouvrir `chrome://extensions` dans Chrome
2. Activer **Mode développeur** (toggle en haut à droite)
3. Cliquer **Charger l'extension non empaquetée**
4. Sélectionner le dossier `extension/`
5. **Copier l'ID** affiché sous "CDP Bridge" (32 lettres)

### Étape 2 — Installer le Native Host

```bash
chmod +x install.sh
./install.sh <extension-id>
```

Le script :
- Crée un launcher pour Node.js
- Génère le manifest native messaging avec l'ID de l'extension
- L'installe dans `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/`

### Étape 3 — Redémarrer Chrome

Fermer et rouvrir Chrome. L'extension se connecte automatiquement au native host.

### Étape 4 — Tester

```bash
# Vérifier que le bridge tourne
curl http://localhost:9222/health

# Lister les onglets
curl http://localhost:9222/json

# Tester depuis Python
python3 chrome-bridge.py status
python3 chrome-bridge.py tab https://www.google.com
python3 chrome-bridge.py screenshot test.png
```

## Migration depuis chrome-shared.py

**Le changement est minimal** — juste remplacer le nom du script :

```bash
# AVANT (CDP direct — login Google bloqué)
python3 chrome-shared.py tab https://google.com
python3 chrome-shared.py screenshot out.png
python3 chrome-shared.py click "#login"

# APRÈS (Extension bridge — login OK)
python3 chrome-bridge.py tab https://google.com
python3 chrome-bridge.py screenshot out.png
python3 chrome-bridge.py click "#login"
```

**Toutes les commandes sont identiques.** La classe `CDP` et la fonction `get_cdp()` ont la même interface.

## Commandes disponibles

Identiques à chrome-shared.py :

| Catégorie | Commandes |
|-----------|-----------|
| **Tabs** | `tab <url>`, `get`, `close`, `list`, `status` |
| **Navigation** | `goto <url>`, `reload`, `back`, `forward`, `url`, `title` |
| **Lecture** | `read <f>`, `read-text <f>`, `read-element <sel> <f>`, `read-attr <sel> <attr>`, `read-links`, `eval <expr>` |
| **Click** | `click <sel>`, `click-text <txt>`, `dblclick <sel>`, `hover <sel>` |
| **Input** | `type <sel> <txt>`, `fill <sel> <txt>`, `clear <sel>`, `press <key>` |
| **Forms** | `select <sel> <val>`, `check <sel>`, `uncheck <sel>`, `submit` |
| **Scroll** | `scroll <dir>`, `scroll-to <sel>` |
| **Wait** | `wait <s>`, `wait-element <sel>`, `wait-hidden <sel>`, `wait-text <txt>` |
| **Capture** | `screenshot <f>`, `screenshot-full <f>`, `pdf <f>` |
| **Images** | `read-images [f]`, `capture-element <sel> <f>`, `download-images <dir>` |

## API HTTP (pour intégration custom)

Le native host expose ces endpoints sur `http://localhost:9222` :

```bash
# CDP-compatible
GET  /json              # Liste des onglets
GET  /json/version      # Version info
PUT  /json/new?<url>    # Créer un onglet
GET  /json/close/<id>   # Fermer un onglet

# Extension bridge
POST /command           # Commande générique
     {"action": "screenshot", "params": {"tabId": 42}}

# Raccourcis
POST /navigate          # {"tabId": 42, "url": "https://..."}
GET  /screenshot        # ?tabId=42&fullPage=true
GET  /pdf               # ?tabId=42
POST /eval              # {"tabId": 42, "expression": "document.title"}

# Monitoring
GET  /health            # État du bridge
```

## La barre jaune

Quand l'extension utilise `chrome.debugger.attach()`, Chrome affiche :
> **"CDP Bridge est en train de déboguer ce navigateur"**

C'est **normal et inoffensif**. Cette barre :
- ✅ N'empêche PAS le login Google
- ✅ N'est PAS détectée comme automation
- ❌ Est visible (cosmétique uniquement)

L'extension garde le debugger attaché pendant l'utilisation.

## Différences avec chrome-shared.py

| Aspect | chrome-shared.py | chrome-bridge.py |
|--------|-----------------|-----------------|
| Transport | WebSocket CDP direct | HTTP → Native Messaging → chrome.debugger |
| Chrome requis | `--remote-debugging-port=9222` | Chrome normal + extension |
| Google login | ❌ Bloqué/détecté | ✅ Fonctionne |
| Dépendances | `websocket-client` | Aucune (stdlib Python) |
| Latence | ~5ms par commande | ~20-50ms par commande |
| Barre jaune | Non | Oui (cosmétique) |
| Redis | Supporté | Supporté (identique) |
| Multi-agent | Supporté | Supporté (identique) |

## Dépannage

### Le bridge ne répond pas (`curl: Connection refused`)

1. Vérifier que Chrome est ouvert
2. Vérifier l'extension dans `chrome://extensions` (doit être active)
3. Vérifier les logs : clic droit sur l'extension → "Inspecter le service worker"
4. Vérifier le manifest : `cat ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/com.cdpbridge.host.json`

### L'extension ne se connecte pas au native host

- Vérifier que l'ID dans le manifest correspond à celui de l'extension
- Vérifier que Node.js est installé : `which node`
- Relancer Chrome après l'installation

### Port 9222 déjà utilisé

Si Chrome tourne encore avec `--remote-debugging-port=9222` :
```bash
# Trouver et tuer le process
lsof -i :9222
kill <PID>
# Relancer Chrome normalement (SANS le flag)
```

### Limite de taille des messages (1 MB)

Les screenshots viewport passent en général (< 500 KB base64).
Les screenshots full-page de très longues pages peuvent dépasser 1 MB.
Solution : réduire `MAX_IMAGE_DIM` ou capturer par sections.

## Fichiers

```
cdp-bridge/
├── README.md                    # Ce fichier
├── install.sh                   # Installeur macOS
├── chrome-bridge.py             # Client Python (drop-in chrome-shared.py)
├── extension/
│   ├── manifest.json            # Extension MV3
│   ├── background.js            # Service worker (cœur)
│   ├── popup.html               # UI de test
│   ├── popup.js                 # Logique popup
│   └── icons/
│       ├── icon16.png
│       ├── icon48.png
│       └── icon128.png
└── native-host/
    ├── cdp-bridge-host.js       # Serveur HTTP + Native Messaging
    └── com.cdpbridge.host.json.template  # Template manifest
```

## Désinstallation

```bash
./install.sh --uninstall
```
Puis retirer l'extension depuis `chrome://extensions`.
