#!/bin/bash
# x45.sh — Gestion des projets et triangles x45
#
# Usage:
#   ./scripts/x45.sh init      <nom-projet>
#   ./scripts/x45.sh create    <id-nom-verbose>
#   ./scripts/x45.sh disable <id>
#   ./scripts/x45.sh enable    <id>
#   ./scripts/x45.sh list
#
# Exemples:
#   ./scripts/x45.sh init      "mon-projet"
#   ./scripts/x45.sh create    "346-audit-securite-api"
#   ./scripts/x45.sh disable 346
#   ./scripts/x45.sh enable    346

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."
PROMPTS_DIR="$ROOT/prompts"
DISABLED_DIR="$ROOT/prompts-disabled"

# Auto-detect MA_PREFIX
if [ -z "${MA_PREFIX:-}" ] && [ -f "$ROOT/project-config.md" ]; then
    MA_PREFIX=$(grep '^MA_PREFIX=' "$ROOT/project-config.md" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
fi
MA_PREFIX="${MA_PREFIX:-ma}"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err()  { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# === Helpers ===

# Find directory matching a numeric ID (plain or verbose)
find_dir() {
    local base_dir="$1"
    local id="$2"
    # Exact match
    if [ -d "$base_dir/$id" ]; then
        echo "$base_dir/$id"
        return 0
    fi
    # Verbose match: 341-analyse-archi-...
    for d in "$base_dir"/${id}-*/; do
        if [ -d "$d" ]; then
            echo "${d%/}"
            return 0
        fi
    done
    return 1
}

# Derive all 6 agent IDs from a base ID
derive_ids() {
    local id="$1"
    SUFFIX="${id:1}"
    MASTER="${id}-1${SUFFIX}"
    OBSERVER="${id}-5${SUFFIX}"
    CURATOR="${id}-7${SUFFIX}"
    COACH="${id}-8${SUFFIX}"
    ARCHITECT="${id}-9${SUFFIX}"
    ALL_AGENTS=("$id" "$MASTER" "$OBSERVER" "$CURATOR" "$COACH" "$ARCHITECT")
}

# Stop all agents of a triangle (agent.sh auto-expands x45)
stop_triangle() {
    local id="$1"
    log_info "Stopping triangle $id..."
    "$SCRIPT_DIR/agent.sh" stop "$id" || log_warn "stop $id returned error"
}

# Start all agents of a triangle (agent.sh auto-expands x45)
start_triangle() {
    local id="$1"
    log_info "Starting triangle $id..."
    "$SCRIPT_DIR/agent.sh" start "$id" || log_warn "start $id returned error"
}

# ============================================================
# INIT
# ============================================================
do_init() {
    local PROJECT_NAME="${1:?Usage: $0 init <nom-projet>}"

    # Sanitize
    PROJECT_NAME=$(echo "$PROJECT_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -cd 'a-z0-9-')

    echo ""
    log_info "Initialisation projet x45 : $PROJECT_NAME"
    echo ""

    # 1. AGENT.md
    if [ -f "$PROMPTS_DIR/AGENT.md" ]; then
        log_ok "prompts/AGENT.md existe déjà"
    elif [ -f "$ROOT/templates/x45/prompts/AGENT.md" ]; then
        cp "$ROOT/templates/x45/prompts/AGENT.md" "$PROMPTS_DIR/AGENT.md"
        log_ok "prompts/AGENT.md copié depuis templates"
    else
        cat > "$PROMPTS_DIR/AGENT.md" << 'AGENTEOF'
# AGENT — Loader universel x45

Tu es un agent du système multi-agent x45.

## Démarrage

1. Lis ton `system.md` (contrat, périmètre, INPUT/OUTPUT)
2. Lis ton `memory.md` (contexte curé)
3. Lis ton `methodology.md` (méthodes)
4. EXÉCUTE immédiatement ta mission

## Règles

- STRICTEMENT OBÉIR à ton system.md
- NE JAMAIS improviser hors de ton périmètre
- NE JAMAIS modifier tes propres fichiers .md (sauf si ton contrat le permet)
- Logging OBLIGATOIRE dans LOGS.md
- Si bloqué → signaler à ton superviseur via Redis
AGENTEOF
        log_ok "prompts/AGENT.md créé"
    fi

    # 2. Agents globaux (flat .md)
    local -A AGENTS
    AGENTS[200]="explorer"
    AGENTS[400]="merge"
    AGENTS[500]="observer"
    AGENTS[600]="indexer"
    AGENTS[700]="curator"
    AGENTS[800]="coach"
    AGENTS[900]="architect"

    local -A ROLES
    ROLES[200]="Explorer — Scan codebase"
    ROLES[400]="Merge — Intégration Git cherry-pick"
    ROLES[500]="Observer global — Bilans et scores"
    ROLES[600]="Indexer global — Index documents pipeline"
    ROLES[700]="Curator global — Préparation memory agents"
    ROLES[800]="Coach global — Amélioration methodology agents"
    ROLES[900]="Architect global — Écriture contrats agents"

    local -A WRITE_PERMS
    WRITE_PERMS[200]="pipeline/200-output/, index/"
    WRITE_PERMS[400]="project/ (merge branches)"
    WRITE_PERMS[500]="bilans/"
    WRITE_PERMS[600]="index/"
    WRITE_PERMS[700]="prompts/*/XXX-memory.md (tous les agents)"
    WRITE_PERMS[800]="prompts/*/XXX-methodology.md (tous les agents)"
    WRITE_PERMS[900]="prompts/*/XXX-system.md, prompts/*/XXX-memory.md (tous les agents)"

    local -A INPUTS
    INPUTS[200]="project-config.md, codebase du projet"
    INPUTS[400]="pipeline/*/output (outputs des 3XX)"
    INPUTS[500]="pipeline/*/output, bilans précédents"
    INPUTS[600]="pipeline/*/output, project/raw/, project/clean/"
    INPUTS[700]="prompts/*/XXX-system.md, pipeline/*/output, index/"
    INPUTS[800]="bilans/, prompts/*/XXX-methodology.md"
    INPUTS[900]="project-config.md, docs/X45-*.md, bilans/"

    local -A OUTPUTS
    OUTPUTS[200]="pipeline/200-output/ (analyse, SPEC)"
    OUTPUTS[400]="branche intégrée (cherry-pick des outputs 3XX)"
    OUTPUTS[500]="bilans/{id}-cycle{N}.md (score 0-100)"
    OUTPUTS[600]="index/ (documents indexés)"
    OUTPUTS[700]="prompts/*/XXX-memory.md mis à jour"
    OUTPUTS[800]="prompts/*/XXX-methodology.md améliorés"
    OUTPUTS[900]="prompts/*/XXX-system.md, prompts/*/XXX-memory.md configurés"

    echo ""
    echo "  Agents globaux :"
    for id in 200 400 500 600 700 800 900; do
        local filename="${id}-${AGENTS[$id]}-${PROJECT_NAME}.md"

        # Skip if already exists (flat .md or directory)
        if ls "$PROMPTS_DIR"/${id}-*.md 1>/dev/null 2>&1 || ls -d "$PROMPTS_DIR"/${id} "$PROMPTS_DIR"/${id}-*/ 1>/dev/null 2>&1; then
            log_ok "  $id déjà présent, skip"
            continue
        fi

        cat > "$PROMPTS_DIR/$filename" << GEOF
# $id — ${ROLES[$id]}

## Identité et périmètre
- **ID** : $id
- **Projet** : $PROJECT_NAME
- **Rôle** : ${ROLES[$id]}
- **Fichiers AUTORISÉS en écriture** : \`${WRITE_PERMS[$id]}\`
- **Communication AUTORISÉE** : \`${MA_PREFIX}:agent:${id}:inbox\`, \`${MA_PREFIX}:agent:${id}:outbox\`, \`${MA_PREFIX}:agent:100:inbox\`

## Contrat
[À configurer par 900 — architect global]

## INPUT
- ${INPUTS[$id]}

## OUTPUT
- ${OUTPUTS[$id]}
- Signal complétion : \`XADD ${MA_PREFIX}:agent:100:inbox * prompt "${id}:done" from_agent "${id}" timestamp "\$(date +%s)"\`

## Critères de succès
[À définir par 900]

## Logging (OBLIGATOIRE)
\`\`\`bash
echo "| \$(date '+%Y-%m-%d %H:%M:%S') | $id | {REMARQUES} | {ERRORS} |" >> logs/${id}.log
\`\`\`
GEOF
        echo "    $filename"
    done

    # 3. Arborescence projet
    echo ""
    echo "  Arborescence :"
    for d in raw clean index pipeline bilans logs; do
        mkdir -p "$ROOT/project/$d"
        echo "    project/$d/"
    done
    mkdir -p "$ROOT/bilans"
    mkdir -p "$ROOT/logs"

    # 4. Redis check
    echo ""
    if command -v redis-cli &>/dev/null && redis-cli ping &>/dev/null 2>&1; then
        log_ok "Redis OK"
    else
        log_warn "Redis non disponible — lancer: ./scripts/infra.sh start"
    fi

    # 5. Summary
    echo ""
    log_ok "Projet x45 '$PROJECT_NAME' initialisé"
    echo ""
    echo "  Prochaines étapes :"
    echo "    1. Éditer prompts/900-*-${PROJECT_NAME}.md (contexte projet)"
    echo "    2. ./scripts/infra.sh start"
    echo "    3. ./scripts/agent.sh start 900"
    echo "    4. ./scripts/send.sh 900 \"go\""
    echo "    5. ./scripts/x45.sh create \"341-nom-tache\""
    echo "    6. ./scripts/agent.sh start all"
    echo ""
}

# ============================================================
# CREATE
# ============================================================
do_create() {
    local INPUT="${1:?Usage: $0 create <id-nom-verbose>  (ex: 341-analyse-archi)}"

    # Extract ID (first 3 chars) and verbose name (rest after the dash)
    local ID="${INPUT:0:3}"
    local VERBOSE_NAME="${INPUT:4}"

    # Validate ID is 3 digits
    if [[ ! "$ID" =~ ^[0-9][0-9][0-9]$ ]]; then
        log_err "Les 3 premiers caractères doivent être des chiffres (ex: 341-analyse-archi)"
        exit 1
    fi

    # Validate verbose name exists
    if [ -z "$VERBOSE_NAME" ]; then
        log_err "Nom verbose manquant (ex: 341-analyse-archi)"
        exit 1
    fi

    # Sanitize verbose name
    VERBOSE_NAME=$(echo "$VERBOSE_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -cd 'a-z0-9-')

    # Humanize role from verbose name (dashes → spaces, capitalize first letter)
    local ROLE
    ROLE=$(echo "$VERBOSE_NAME" | tr '-' ' ' | sed 's/^\(.\)/\U\1/')

    # Check not already existing (active or disabled)
    if find_dir "$PROMPTS_DIR" "$ID" >/dev/null 2>&1; then
        log_err "Triangle $ID existe déjà dans prompts/"
        exit 1
    fi
    if find_dir "$DISABLED_DIR" "$ID" >/dev/null 2>&1; then
        log_err "Triangle $ID existe dans prompts-disabled/ — utiliser 'enable' d'abord"
        exit 1
    fi

    derive_ids "$ID"
    local DIR_NAME="${ID}-${VERBOSE_NAME}"
    local DIR="$PROMPTS_DIR/$DIR_NAME"

    echo ""
    log_info "Création triangle $ID ($ROLE)"
    echo "  Répertoire : prompts/$DIR_NAME/"
    echo ""
    echo "  $ID          Main ($ROLE)"
    echo "  $MASTER   Local Master"
    echo "  $OBSERVER   Observer"
    echo "  $CURATOR   Curator"
    echo "  $COACH   Coach"
    echo "  $ARCHITECT   Triangle Architect"
    echo ""

    mkdir -p "$DIR"

    # Helper: create AGENT.md symlink
    mk_sym() { ln -sf ../AGENT.md "$DIR/${1}.md"; }

    # --- Main (worker) ---
    mk_sym "$ID"
    cat > "$DIR/${ID}-system.md" << SEOF
# $ID — $ROLE

## Identité et périmètre
- **ID** : $ID
- **Triangle** : $ID
- **Rôle** : Main ($ROLE)
- **Fichiers AUTORISÉS en écriture** : \`pipeline/${ID}-output/\`, \`prompts/$DIR_NAME/LOGS.md\` (append)
- **Communication AUTORISÉE** : \`${MA_PREFIX}:agent:${ID}:inbox\`, \`${MA_PREFIX}:agent:${ID}:outbox\`, \`${MA_PREFIX}:agent:${MASTER}:inbox\`

## Contrat
[À configurer par $ARCHITECT]

## INPUT
- \`${ID}-memory.md\` (contexte curé par $CURATOR)
- [output du maillon précédent]

## OUTPUT
- Résultat dans \`pipeline/${ID}-output/\`
- Signal complétion : \`XADD ${MA_PREFIX}:agent:${MASTER}:inbox * prompt "${ID}:done" from_agent "${ID}" timestamp "\$(date +%s)"\`

## Critères de succès
[À définir par $ARCHITECT]

## Logging (OBLIGATOIRE)
\`\`\`bash
echo "| \$(date '+%Y-%m-%d %H:%M:%S') | $ID | {REMARQUES} | {ERRORS} |" >> prompts/$DIR_NAME/LOGS.md
\`\`\`

## Ce que tu NE fais PAS
- Tu ne t'auto-évalues PAS (c'est $OBSERVER)
- Tu ne modifies PAS tes fichiers md
SEOF
    cat > "$DIR/${ID}-memory.md" << SEOF
# $ID — Memory
[Curé par $CURATOR]
## Tâche en cours
[Assignée par le pipeline]
## Données pertinentes
[Préparées par $CURATOR]
SEOF
    cat > "$DIR/${ID}-methodology.md" << SEOF
# $ID — Methodology
## Process
[À définir. Sera amélioré par $COACH.]
## Changelog
SEOF

    # --- Local Master (1XX) ---
    mk_sym "$MASTER"
    cat > "$DIR/${MASTER}-system.md" << SEOF
# $MASTER — Local Master du triangle $ID

## Identité et périmètre
- **ID** : $MASTER
- **Triangle** : $ID
- **Rôle** : Local Master
- **Fichiers AUTORISÉS en écriture** : \`prompts/$DIR_NAME/LOGS.md\` (append) — AUCUN AUTRE
- **Fichiers INTERDITS** : TOUS les autres fichiers — tu ne fais que dispatcher via Redis
- **Communication AUTORISÉE** : \`${MA_PREFIX}:agent:${MASTER}:inbox\`, \`${MA_PREFIX}:agent:${MASTER}:outbox\`, \`${MA_PREFIX}:agent:${ARCHITECT}:inbox\`, \`${MA_PREFIX}:agent:${CURATOR}:inbox\`, \`${MA_PREFIX}:agent:${ID}:inbox\`, \`${MA_PREFIX}:agent:${OBSERVER}:inbox\`, \`${MA_PREFIX}:agent:${COACH}:inbox\`, \`${MA_PREFIX}:agent:100:inbox\`

## Contrat
Tu orchestres la boucle qualité du triangle $ID ($ROLE).
Tu dispatches les agents satellites dans l'ordre, tu lis les scores de l'Observer,
et tu décides de continuer ou d'arrêter la boucle.

## INPUT
- Redis inbox : \`${MA_PREFIX}:agent:${MASTER}:inbox\` (dispatch de 100, retours des satellites)
- \`bilans/${ID}-cycle*.md\` (scores de $OBSERVER Observer)

## OUTPUT
- Dispatch Redis vers les 5 agents du triangle ($ARCHITECT, $CURATOR, $ID, $OBSERVER, $COACH)
- Signal complétion : \`XADD ${MA_PREFIX}:agent:100:inbox * prompt "${MASTER}:done" from_agent "${MASTER}" timestamp "\$(date +%s)"\`

## Agents du triangle
| ID | Rôle | Quand |
|----|------|-------|
| $ARCHITECT | Triangle Architect | Phase 0 (bootstrap) + boucle longue |
| $CURATOR | Curator | Début de chaque cycle |
| $ID | Main ($ROLE) | Après Curator |
| $OBSERVER | Observer | Après Main → produit score |
| $COACH | Coach | Boucle courte (score < 98%) |

## Critères de succès
- Chaque cycle exécuté dans l'ordre : $CURATOR → $ID → $OBSERVER → décision
- Score ≥ 98% maintenu 2 cycles consécutifs → DONE
- Maximum 6 cycles avant DONE forcé

## Logging (OBLIGATOIRE)
\`\`\`bash
echo "| \$(date '+%Y-%m-%d %H:%M:%S') | $MASTER | {REMARQUES} | {ERRORS} |" >> prompts/$DIR_NAME/LOGS.md
\`\`\`

## Ce que tu NE fais PAS
- Tu n'exécutes PAS la tâche de $ID
- Tu n'évalues PAS la qualité (c'est $OBSERVER)
- Tu ne réécris PAS les prompts (c'est $COACH/$ARCHITECT)
SEOF
    cat > "$DIR/${MASTER}-memory.md" << SEOF
# $MASTER — Memory
## Triangle $ID
- Main: $ID ($ROLE)
- Satellites: $OBSERVER, $CURATOR, $COACH, $ARCHITECT
## État
Cycle: 0 (pas encore démarré)
SEOF
    cat > "$DIR/${MASTER}-methodology.md" << SEOF
# $MASTER — Methodology
## Boucle qualité
1. Phase 0 : dispatch $ARCHITECT (bootstrap system.md)
2. Cycle N :
   a. Dispatch $CURATOR (prépare memory.md)
   b. Dispatch $ID (exécute la tâche)
   c. Dispatch $OBSERVER (évalue → score)
   d. Si score < 98% : dispatch $COACH (améliore methodology)
   e. Si score ≥ 98% × 2 cycles : DONE
3. Max 6 cycles → DONE forcé
## Changelog
SEOF

    # --- Observer (5XX) ---
    mk_sym "$OBSERVER"
    cat > "$DIR/${OBSERVER}-system.md" << SEOF
# $OBSERVER — Observer de $ID

## Identité et périmètre
- **ID** : $OBSERVER
- **Triangle** : $ID
- **Rôle** : Observer
- **Fichiers AUTORISÉS en écriture** : \`bilans/${ID}-cycle*.md\`, \`prompts/$DIR_NAME/LOGS.md\` (append)
- **Communication AUTORISÉE** : \`${MA_PREFIX}:agent:${OBSERVER}:inbox\`, \`${MA_PREFIX}:agent:${OBSERVER}:outbox\`, \`${MA_PREFIX}:agent:${MASTER}:inbox\`

## Contrat
Tu évalues la qualité de l'output produit par $ID.

## INPUT
- \`pipeline/${ID}-output/\` (output de $ID)
- \`prompts/$DIR_NAME/${ID}-system.md\` (critères de succès)

## OUTPUT
- \`bilans/${ID}-cycle{N}.md\` (score 0-100 + détail par métrique)
- Signal : \`XADD ${MA_PREFIX}:agent:${MASTER}:inbox * prompt "${OBSERVER}:done:score:{SCORE}" from_agent "${OBSERVER}" timestamp "\$(date +%s)"\`

## Logging (OBLIGATOIRE)
\`\`\`bash
echo "| \$(date '+%Y-%m-%d %H:%M:%S') | $OBSERVER | {REMARQUES} | {ERRORS} |" >> prompts/$DIR_NAME/LOGS.md
\`\`\`

## Ce que tu NE fais PAS
- Tu ne corriges PAS l'output
- Tu ne réécris PAS les prompts
SEOF
    cat > "$DIR/${OBSERVER}-memory.md" << SEOF
# $OBSERVER — Memory
## Agent cible : $ID
## Critères d'évaluation
[Extraits de ${ID}-system.md par $ARCHITECT]
SEOF
    cat > "$DIR/${OBSERVER}-methodology.md" << SEOF
# $OBSERVER — Methodology
## Process d'évaluation
1. Lire ${ID}-system.md pour les critères de succès
2. Lire l'output dans pipeline/${ID}-output/
3. Évaluer chaque critère (0-100)
4. Score global = moyenne pondérée
5. Écrire bilan dans bilans/${ID}-cycle{N}.md
6. Signaler score à $MASTER
## Changelog
SEOF

    # --- Curator (7XX) ---
    mk_sym "$CURATOR"
    cat > "$DIR/${CURATOR}-system.md" << SEOF
# $CURATOR — Curator de $ID

## Identité et périmètre
- **ID** : $CURATOR
- **Triangle** : $ID
- **Rôle** : Curator
- **Fichiers AUTORISÉS en écriture** : \`prompts/$DIR_NAME/${ID}-memory.md\`, \`prompts/$DIR_NAME/LOGS.md\` (append)
- **Communication AUTORISÉE** : \`${MA_PREFIX}:agent:${CURATOR}:inbox\`, \`${MA_PREFIX}:agent:${CURATOR}:outbox\`, \`${MA_PREFIX}:agent:${MASTER}:inbox\`

## Contrat
Tu prépares le memory.md de $ID en extrayant les données pertinentes pour sa tâche.

## INPUT
- \`prompts/$DIR_NAME/${ID}-system.md\` (besoins de $ID)
- \`prompts/$DIR_NAME/${ID}-methodology.md\`
- Données source (pipeline précédent, index, etc.)

## OUTPUT
- \`prompts/$DIR_NAME/${ID}-memory.md\` (budget : 2000 tokens max)
- Signal : \`XADD ${MA_PREFIX}:agent:${MASTER}:inbox * prompt "${CURATOR}:done" from_agent "${CURATOR}" timestamp "\$(date +%s)"\`

## Logging (OBLIGATOIRE)
\`\`\`bash
echo "| \$(date '+%Y-%m-%d %H:%M:%S') | $CURATOR | {REMARQUES} | {ERRORS} |" >> prompts/$DIR_NAME/LOGS.md
\`\`\`

## Ce que tu NE fais PAS
- Tu n'exécutes PAS la tâche de $ID
- Tu ne modifies PAS system.md ni methodology.md
SEOF
    cat > "$DIR/${CURATOR}-memory.md" << SEOF
# $CURATOR — Memory
## Agent cible : $ID
## Tâche en cours de $ID
[À remplir]
## Sources de données
[À remplir]
SEOF
    cat > "$DIR/${CURATOR}-methodology.md" << SEOF
# $CURATOR — Methodology
## Process de curation
1. Lire system.md et methodology.md de $ID
2. Identifier les données nécessaires
3. Extraire des sources pertinentes
4. Filtrer par pertinence
5. Assembler memory.md (max 2000 tokens)
## Changelog
SEOF

    # --- Coach (8XX) ---
    mk_sym "$COACH"
    cat > "$DIR/${COACH}-system.md" << SEOF
# $COACH — Coach de $ID

## Identité et périmètre
- **ID** : $COACH
- **Triangle** : $ID
- **Rôle** : Coach
- **Fichiers AUTORISÉS en écriture** : \`prompts/$DIR_NAME/${ID}-methodology.md\`, \`prompts/$DIR_NAME/LOGS.md\` (append)
- **Communication AUTORISÉE** : \`${MA_PREFIX}:agent:${COACH}:inbox\`, \`${MA_PREFIX}:agent:${COACH}:outbox\`, \`${MA_PREFIX}:agent:${MASTER}:inbox\`

## Contrat
Tu améliores la methodology.md de $ID en analysant les bilans de $OBSERVER.

## INPUT
- \`bilans/${ID}-cycle*.md\` (bilans d'évaluation par $OBSERVER)
- \`prompts/$DIR_NAME/${ID}-methodology.md\` actuel

## OUTPUT
- \`prompts/$DIR_NAME/${ID}-methodology.md\` amélioré
- Signal : \`XADD ${MA_PREFIX}:agent:${MASTER}:inbox * prompt "${COACH}:done" from_agent "${COACH}" timestamp "\$(date +%s)"\`

## Logging (OBLIGATOIRE)
\`\`\`bash
echo "| \$(date '+%Y-%m-%d %H:%M:%S') | $COACH | {REMARQUES} | {ERRORS} |" >> prompts/$DIR_NAME/LOGS.md
\`\`\`

## Ce que tu NE fais PAS
- Tu ne modifies PAS system.md (c'est $ARCHITECT)
- Tu ne modifies PAS memory.md (c'est $CURATOR)
- Si problème de contrat → escalade vers $ARCHITECT
SEOF
    cat > "$DIR/${COACH}-memory.md" << SEOF
# $COACH — Memory
## Agent cible : $ID
## Bilans récents
[Extraits des bilans $OBSERVER]
## Historique améliorations
[Log]
SEOF
    cat > "$DIR/${COACH}-methodology.md" << SEOF
# $COACH — Methodology
## Process d'amélioration
1. Lire bilans $OBSERVER de $ID
2. Identifier échecs récurrents
3. Classifier : methodology / memory / system
4. Réécrire section concernée de methodology.md
5. Ajouter au changelog
## Escalade vers $ARCHITECT
Condition : 3 cycles sans amélioration.
## Changelog
SEOF

    # --- Triangle Architect (9XX) ---
    mk_sym "$ARCHITECT"
    cat > "$DIR/${ARCHITECT}-system.md" << SEOF
# $ARCHITECT — Triangle Architect de $ID

## Identité et périmètre
- **ID** : $ARCHITECT
- **Triangle** : $ID
- **Rôle** : Triangle Architect
- **Fichiers AUTORISÉS en écriture** :
  - \`prompts/$DIR_NAME/${ID}-system.md\`, \`prompts/$DIR_NAME/${ID}-memory.md\`
  - \`prompts/$DIR_NAME/${MASTER}-system.md\`, \`prompts/$DIR_NAME/${MASTER}-memory.md\`
  - \`prompts/$DIR_NAME/${OBSERVER}-system.md\`, \`prompts/$DIR_NAME/${OBSERVER}-memory.md\`
  - \`prompts/$DIR_NAME/${CURATOR}-system.md\`, \`prompts/$DIR_NAME/${CURATOR}-memory.md\`
  - \`prompts/$DIR_NAME/${COACH}-system.md\`, \`prompts/$DIR_NAME/${COACH}-memory.md\`
  - \`prompts/$DIR_NAME/${ARCHITECT}-memory.md\`
  - \`prompts/$DIR_NAME/LOGS.md\` (append)
- **Communication AUTORISÉE** : \`${MA_PREFIX}:agent:${ARCHITECT}:inbox\`, \`${MA_PREFIX}:agent:${ARCHITECT}:outbox\`, \`${MA_PREFIX}:agent:${MASTER}:inbox\`

## Contrat
Tu écris les system.md et memory.md de tous les agents du triangle $ID.
Tu configures le triangle pour que $ID puisse accomplir sa mission : $ROLE.

## INPUT
- Contexte projet (project-config.md, pipeline précédent)
- \`docs/X45-ARCHITECTURE.md\`, \`docs/X45-CONVENTIONS.md\`

## OUTPUT
- system.md + memory.md pour les 5 autres agents du triangle
- Signal : \`XADD ${MA_PREFIX}:agent:${MASTER}:inbox * prompt "${ARCHITECT}:done" from_agent "${ARCHITECT}" timestamp "\$(date +%s)"\`

## Logging (OBLIGATOIRE)
\`\`\`bash
echo "| \$(date '+%Y-%m-%d %H:%M:%S') | $ARCHITECT | {REMARQUES} | {ERRORS} |" >> prompts/$DIR_NAME/LOGS.md
\`\`\`

## Ce que tu NE fais PAS
- Tu n'écris PAS les methodology.md (c'est $COACH)
- Tu n'exécutes PAS la tâche de $ID
- Tu n'écris PAS ton propre system.md
SEOF
    cat > "$DIR/${ARCHITECT}-memory.md" << SEOF
# $ARCHITECT — Memory
## Triangle $ID — $ROLE
| ID | Rôle |
|----|------|
| $ID | Main ($ROLE) |
| $MASTER | Local Master |
| $OBSERVER | Observer |
| $CURATOR | Curator |
| $COACH | Coach |
| $ARCHITECT | Triangle Architect |
## Contexte projet
[À remplir par 900 ou manuellement]
SEOF
    cat > "$DIR/${ARCHITECT}-methodology.md" << SEOF
# $ARCHITECT — Methodology
## Process bootstrap
1. Lire le contexte projet et la doc X45
2. Définir les critères de succès de $ID
3. Écrire system.md de $ID (contrat, INPUT, OUTPUT, critères)
4. Écrire system.md de $MASTER (agents, ordre, critères arrêt)
5. Écrire system.md de $OBSERVER (métriques d'évaluation)
6. Écrire system.md de $CURATOR (sources de données)
7. Écrire system.md de $COACH (critères d'amélioration)
8. Signaler complétion à $MASTER
## Changelog
SEOF

    # --- LOGS.md ---
    cat > "$DIR/LOGS.md" << SEOF
| Date | Agent | Remarques | Errors |
|------|-------|-----------|--------|
SEOF

    # --- Pipeline output ---
    mkdir -p "$ROOT/pipeline/${ID}-output" 2>/dev/null || true

    local TOTAL
    TOTAL=$(ls "$DIR"/*.md | wc -l)
    echo ""
    log_ok "Triangle $ID créé ($TOTAL fichiers dans prompts/$DIR_NAME/)"

    # Start agents
    start_triangle "$ID"

    echo ""
    log_ok "Triangle $ID prêt. Lancer avec: ./scripts/send.sh $MASTER \"go\""
}

# ============================================================
# DESACTIVE
# ============================================================
do_disable() {
    local ID="${1:?Usage: $0 disable <id>}"

    if [[ ! "$ID" =~ ^[0-9][0-9][0-9]$ ]]; then
        log_err "L'ID doit être 3 chiffres (ex: 346)"
        exit 1
    fi

    local DIR
    DIR=$(find_dir "$PROMPTS_DIR" "$ID") || {
        log_err "Triangle $ID non trouvé dans prompts/"
        exit 1
    }

    # Stop agents first
    stop_triangle "$ID"

    # Move to disabled
    mkdir -p "$DISABLED_DIR"
    mv "$DIR" "$DISABLED_DIR/"
    local DIRNAME
    DIRNAME=$(basename "$DIR")

    log_ok "Triangle $ID désactivé : prompts-disabled/$DIRNAME/"
}

# ============================================================
# ACTIVE
# ============================================================
do_enable() {
    local ID="${1:?Usage: $0 enable <id>}"

    if [[ ! "$ID" =~ ^[0-9][0-9][0-9]$ ]]; then
        log_err "L'ID doit être 3 chiffres (ex: 346)"
        exit 1
    fi

    # Check not already active
    if find_dir "$PROMPTS_DIR" "$ID" >/dev/null 2>&1; then
        log_err "Triangle $ID existe déjà dans prompts/"
        exit 1
    fi

    # Find in disabled
    local DIR
    DIR=$(find_dir "$DISABLED_DIR" "$ID") || {
        log_err "Triangle $ID non trouvé dans prompts-disabled/"
        exit 1
    }

    # Move back to prompts
    mv "$DIR" "$PROMPTS_DIR/"
    local DIRNAME
    DIRNAME=$(basename "$DIR")

    log_ok "Triangle $ID activé : prompts/$DIRNAME/"

    # Start agents
    start_triangle "$ID"

    log_ok "Triangle $ID démarré"
}

# ============================================================
# LIST
# ============================================================
do_list() {
    echo "=== Triangles actifs (prompts/) ==="
    local found=0
    for d in "$PROMPTS_DIR"/[0-9][0-9][0-9] "$PROMPTS_DIR"/[0-9][0-9][0-9]-*/; do
        [ -d "$d" ] || continue
        local dirname=$(basename "$d")
        local id="${dirname:0:3}"
        # Must have {id}-system.md or {id}.md symlink
        { [ -f "$d/${id}-system.md" ] || [ -f "$d/${id}.md" ]; } || continue
        local agents=$(ls "$d"/${id}*.md 2>/dev/null | grep -cvE '(system|memory|methodology)' || true)
        echo -e "  ${GREEN}$id${NC}  $dirname/  ($agents agents)"
        found=$((found + 1))
    done
    [ "$found" -eq 0 ] && echo "  (aucun)"

    echo ""
    echo "=== Triangles désactivés (prompts-disabled/) ==="
    found=0
    if [ -d "$DISABLED_DIR" ]; then
        for d in "$DISABLED_DIR"/[0-9][0-9][0-9] "$DISABLED_DIR"/[0-9][0-9][0-9]-*/; do
            [ -d "$d" ] || continue
            local dirname=$(basename "$d")
            local id="${dirname:0:3}"
            echo -e "  ${YELLOW}$id${NC}  $dirname/"
            found=$((found + 1))
        done
    fi
    [ "$found" -eq 0 ] && echo "  (aucun)"
}

# ============================================================
# HELP
# ============================================================
show_help() {
    echo "Usage: $0 <action> [args...]"
    echo ""
    echo "Actions:"
    echo "  init <nom-projet>          Initialiser un projet x45 (agents globaux + arborescence)"
    echo "  create <id-nom>           Créer un triangle x45 complet (6 agents) + démarrer"
    echo "  disable <id>            Stopper les agents + déplacer dans prompts-disabled/"
    echo "  enable <id>               Réactiver depuis prompts-disabled/ + démarrer"
    echo "  list                      Lister les triangles actifs et désactivés"
    echo ""
    echo "Exemples:"
    echo "  $0 init      \"mon-projet\""
    echo "  $0 create    \"346-audit-securite-api\""
    echo "  $0 disable 346"
    echo "  $0 enable    346"
}

# ============================================================
# MAIN
# ============================================================
ACTION="${1:-}"
shift 2>/dev/null || true

case "$ACTION" in
    i|init)       do_init "$@" ;;
    c|create)     do_create "$@" ;;
    d|disable)    do_disable "$@" ;;
    e|enable)     do_enable "$@" ;;
    l|list)       do_list ;;
    -h|--help|help|"") show_help ;;
    *)       log_err "Action inconnue: $ACTION"; show_help; exit 1 ;;
esac
