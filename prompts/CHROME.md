INTERDICTION D'HALUCINER
OBLIGATION d'OBEIR AUX PROMPTS. NE JAMAIS SORTIR DU CADRE DEFINIS PAR LE PROMPT
APPRENTISSAGE: Quand je suis guidé par un humain et que je reçois des instructions AUTRES que "go <entreprise>", c'est du nouveau savoir. Je DOIS mettre à jour mon prompt avec ces nouvelles expériences pour être autonome la prochaine fois.

# Chrome Partagé - CDP

**UN SEUL Chrome** pour tous les agents sur port 9222.
Méthode: CDP (Chrome DevTools Protocol) via WebSocket.

---

## Commandes

Toutes les commandes utilisent `python3 $BASE/scripts/chrome-bridge.py <cmd> [args]`.

### Navigation

```bash
tab "https://url"          # Créer onglet + naviguer
goto "https://url"         # Naviguer (onglet existant)
reload                     # Rafraîchir
back                       # Page précédente
forward                    # Page suivante
url                        # Afficher URL actuelle
title                      # Afficher titre
```

### Lecture

```bash
read output.html           # HTML complet → fichier
read-text output.txt       # Texte seul → fichier
read-element "#div" out    # HTML d'un élément → fichier
read-attr "#img" src       # Valeur d'un attribut
read-links                 # Lister tous les liens
eval "document.title"      # Exécuter JS
```

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

### Captures

```bash
screenshot page.png        # Screenshot viewport
screenshot-full page.png   # Screenshot page entière
pdf output.pdf             # Export PDF
```

### Images (extraction sans screenshot)

```bash
read-images                # Liste toutes les images (JSON stdout)
read-images images.json    # Sauvegarde liste images en JSON
capture-element "#chart" chart.png  # Capture un élément spécifique
download-images ./images/  # Télécharge toutes les images
```

**Types d'images extraites :**
- `img` : images `<img src="...">`
- `svg` : SVG inline (convertis en data URI)
- `canvas` : graphiques Canvas (convertis en PNG)
- `background` : images CSS background-image
- `picture` : images responsive `<picture><source>`

**Exemple sortie `read-images` :**
```json
[
  {"type": "img", "src": "https://...", "width": 800, "height": 400, "selector": "#traffic-chart"},
  {"type": "canvas", "src": "data:image/png;base64,...", "width": 600, "height": 300, "selector": "canvas:nth-of-type(1)"},
  {"type": "svg", "src": "data:image/svg+xml;base64,...", "width": 200, "height": 100, "selector": "#logo"}
]
```

### Gestion onglets

```bash
get                        # Récupérer mon tabId
close                      # Fermer mon onglet
list                       # Lister mappings agent→tab
status                     # Statut Chrome
```

---

## Exemple complet: SimilarWeb

```bash
# 1. Créer onglet et naviguer
python3 $BASE/scripts/chrome-bridge.py tab "https://www.similarweb.com"

# 2. Attendre chargement
python3 $BASE/scripts/chrome-bridge.py wait 3

# 3. Accepter cookies si présent
python3 $BASE/scripts/chrome-bridge.py click-text "Accept" || true

# 4. Taper dans la recherche
python3 $BASE/scripts/chrome-bridge.py type "input[type=search]" "example.com"

# 5. Appuyer Entrée
python3 $BASE/scripts/chrome-bridge.py press enter

# 6. Attendre résultats
python3 $BASE/scripts/chrome-bridge.py wait 5

# 7. Scroll pour charger plus
python3 $BASE/scripts/chrome-bridge.py scroll bottom

# 8. Sauvegarder HTML
python3 $BASE/scripts/chrome-bridge.py read 306/similarweb.html

# 9. Extraire les graphiques (canvas, SVG) sans screenshot
python3 $BASE/scripts/chrome-bridge.py read-images 306/images.json
python3 $BASE/scripts/chrome-bridge.py download-images 306/images/

# 10. OU screenshot classique
python3 $BASE/scripts/chrome-bridge.py screenshot 306/similarweb.png

# 11. Fermer
python3 $BASE/scripts/chrome-bridge.py close
```

---

## Exemple: Ahrefs

```bash
# Naviguer
python3 $BASE/scripts/chrome-bridge.py tab "https://ahrefs.com/backlink-checker"

python3 $BASE/scripts/chrome-bridge.py wait 2

# Remplir le champ
python3 $BASE/scripts/chrome-bridge.py type "input[name=target]" "example.com"

# Soumettre
python3 $BASE/scripts/chrome-bridge.py press enter

# Attendre résultats
python3 $BASE/scripts/chrome-bridge.py wait-element ".BacklinkStats"

# Lire
python3 $BASE/scripts/chrome-bridge.py read 306/ahrefs.html
```

---

## Raccourci alias

Pour simplifier, dans ton script bash:

```bash
CHROME="python3 $BASE/scripts/chrome-bridge.py"

$CHROME tab "https://example.com"
$CHROME wait 2
$CHROME click-text "Accept"
$CHROME read output.html
$CHROME close
```

---

## INTERDIT

```
╔═══════════════════════════════════════════════════════════════╗
║  ⛔ JAMAIS arrêter Chrome (sessions perdues)                  ║
║  ⛔ JAMAIS relancer Chrome automatiquement                    ║
║  ⛔ JAMAIS fermer le dernier tab                              ║
║  ⛔ JAMAIS lancer un 2ème Chrome                              ║
║  ⛔ JAMAIS utiliser Playwright                                ║
║  ⛔ JAMAIS utiliser MCP chrome-devtools                       ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## Codes de sortie

| Code | Signification | Action |
|------|---------------|--------|
| `0` | Succès | Continuer |
| `1` | Erreur générique | Retry possible |
| **`100`** | **CHROME PAS LANCÉ** | **ARRÊT IMMÉDIAT - Alerter user** |
| `101` | Target obsolète | Auto-cleanup fait |
| `102` | WebSocket timeout | Retry 1x |

### RÈGLE CRITIQUE: Code 100

**SI `chrome-bridge.py` retourne code 100 → ARRÊT TOTAL**

```bash
# INTERDIT - NE JAMAIS FAIRE:
open -a "Google Chrome"                    # ❌ CATASTROPHE
/Applications/.../Google\ Chrome ...       # ❌ PERTE SESSIONS
```

```bash
# OBLIGATOIRE - Signaler et attendre:
echo "❌ Chrome non actif - intervention manuelle requise"
exit 1
```

Les sessions (Ahrefs Pro, SimilarWeb Pro, etc.) seraient **PERDUES** si Chrome est relancé automatiquement.

---

## Dépannage

**Chrome non actif:**
```bash
$BASE/scripts/chrome.sh status
# Si non actif, demander à l'utilisateur de le lancer
```

**Element non trouvé:**
```bash
# Ajouter wait avant click
python3 $BASE/scripts/chrome-bridge.py wait 2
python3 $BASE/scripts/chrome-bridge.py wait-element "#button"
python3 $BASE/scripts/chrome-bridge.py click "#button"
```

**Timeout:**
```bash
# Augmenter le wait
python3 $BASE/scripts/chrome-bridge.py wait 5
```

---

*Chrome Partagé v3.1 - CDP complet + sécurité exit codes*
