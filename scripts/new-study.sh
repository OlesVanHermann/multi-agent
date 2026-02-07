#!/bin/bash
# ============================================================================
# new-study.sh - Créer une nouvelle étude avec la structure complète
# ============================================================================
# Usage: ./scripts/new-study.sh <domain>
# Exemple: ./scripts/new-study.sh example.com
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
STUDIES_DIR="$BASE_DIR/studies"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Vérifier l'argument
if [ -z "$1" ]; then
    echo -e "${RED}Usage: $0 <domain>${NC}"
    echo "Exemple: $0 example.com"
    exit 1
fi

DOMAIN="$1"
STUDY_DIR="$STUDIES_DIR/$DOMAIN"

# Vérifier si l'étude existe déjà
if [ -d "$STUDY_DIR" ]; then
    echo -e "${RED}Erreur: L'étude '$DOMAIN' existe déjà${NC}"
    exit 1
fi

echo -e "${GREEN}Création de l'étude: $DOMAIN${NC}"

# Créer la structure des répertoires
mkdir -p "$STUDY_DIR"

# Répertoires de données 300 (crawl) - ignorés par Git
DATA_DIRS_300=(
    "300/html"
    "300/INDEX"
    "300/FAILED"
    "300/TODO"
)

# Répertoires de données 301 (extraction) - ignorés par Git
DATA_DIRS_301=(
    "301/txt"
    "301/FAILED"
)

# Répertoires de sortie pour les agents d'analyse
# Les agents 3XX écrivent dans ces répertoires
OUTPUT_DIRS=(
    "302"   # SEO technique (agents 320-323)
    "303"   # Réputation (agents 330-336)
    "304"   # Performance (agents 340-347)
    "305"   # Entreprise (agents 350-354)
    "306"   # SEO/SEM (agents 360-365)
    "307"   # Rapport final (agent 370)
    "308"   # Diff (agents 380-382)
)

# Créer les répertoires 300 avec .gitignore
for dir in "${DATA_DIRS_300[@]}"; do
    mkdir -p "$STUDY_DIR/$dir"
    cat > "$STUDY_DIR/$dir/.gitignore" << 'EOF'
# Ignorer tout le contenu sauf ce fichier
*
!.gitignore
EOF
    echo -e "  ${YELLOW}✓${NC} $dir/ (données ignorées)"
done

# Créer les répertoires 301 avec .gitignore
for dir in "${DATA_DIRS_301[@]}"; do
    mkdir -p "$STUDY_DIR/$dir"
    cat > "$STUDY_DIR/$dir/.gitignore" << 'EOF'
# Ignorer tout le contenu sauf ce fichier
*
!.gitignore
EOF
    echo -e "  ${YELLOW}✓${NC} $dir/ (données ignorées)"
done

# Créer les répertoires de sortie avec leur FAILED/
for dir in "${OUTPUT_DIRS[@]}"; do
    mkdir -p "$STUDY_DIR/$dir/FAILED"
    touch "$STUDY_DIR/$dir/.gitkeep"
    cat > "$STUDY_DIR/$dir/FAILED/.gitignore" << 'EOF'
# Ignorer tout le contenu sauf ce fichier
*
!.gitignore
EOF
    echo -e "  ${GREEN}✓${NC} $dir/ + ${YELLOW}FAILED/${NC}"
done

# Créer le .gitignore racine
cat > "$STUDY_DIR/.gitignore" << 'EOF'
# Fichiers temporaires
*.tmp
*.log
.DS_Store
.~lock.*
EOF

# Créer le CLAUDE.md de l'étude
cat > "$STUDY_DIR/CLAUDE.md" << EOF
# Étude: $DOMAIN

## Structure des répertoires

\`\`\`
$DOMAIN/
├── 300/           # Crawl (agent 300)
│   ├── html/      # Pages HTML brutes (ignoré)
│   ├── INDEX/     # Mapping sha256→url (ignoré)
│   ├── FAILED/    # URLs en échec (ignoré)
│   └── TODO/      # URLs à traiter (ignoré)
├── 301/           # Extraction (agent 301)
│   ├── txt/       # Texte extrait (ignoré)
│   └── FAILED/    # Extractions échouées (ignoré)
├── 302/           # SEO technique (agents 320-323)
├── 303/           # Réputation (agents 330-336)
├── 304/           # Performance (agents 340-347)
├── 305/           # Entreprise (agents 350-354)
├── 306/           # SEO/SEM (agents 360-365)
├── 307/           # Rapport final (agent 370)
├── 308/           # Diff (agents 380-382)
└── CLAUDE.md      # Ce fichier
\`\`\`

## Agents

| Répertoire | Agents | Domaine |
|------------|--------|---------|
| 300/ | 300 | Crawl (Python) |
| 301/ | 301 | Extraction (Python) |
| 302/ | 320-323 | SEO technique |
| 303/ | 330-336 | Réputation |
| 304/ | 340-347 | Performance |
| 305/ | 350-354 | Entreprise |
| 306/ | 360-365 | SEO/SEM |
| 307/ | 370 | Rapport final |
| 308/ | 380-382 | Diff |

## Principe

**1 AGENT = 1 TÂCHE = 1 LIVRABLE**

## Workflow

1. **Crawl (300)**: \`python framework/crawl.py $DOMAIN\`
2. **Extract (301)**: \`python framework/extract.py $DOMAIN\`
3. **Analyse (320+)**: Agents LLM + Chrome MCP
4. **Rapport (370)**: Consolidation finale
5. **Diff (380-382)**: Comparaison avec version précédente

## Git SNAPs

\`\`\`bash
# Créer un SNAP après analyse
cd studies/$DOMAIN
git add -A && git commit -m "SNAP-YYYYMMDD: description"
git tag SNAP-YYYYMMDD
\`\`\`
EOF

# Initialiser Git
cd "$STUDY_DIR"
git init -q
git add -A
git commit -q -m "Initial: structure de l'étude $DOMAIN"

echo ""
echo -e "${GREEN}✓ Étude '$DOMAIN' créée avec succès${NC}"
echo ""
echo "Structure:"
echo "  $STUDY_DIR/"
tree -a -L 3 "$STUDY_DIR" 2>/dev/null || find "$STUDY_DIR" -maxdepth 3 -type d | grep -v ".git/" | sort

echo ""
echo -e "Prochaines étapes:"
echo -e "  1. ${YELLOW}python framework/crawl.py $DOMAIN${NC}"
echo -e "  2. ${YELLOW}python framework/extract.py $DOMAIN${NC}"
