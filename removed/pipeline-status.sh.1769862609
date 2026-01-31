#!/bin/bash
#
# Pipeline Status - Vue complète de l'état
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
PR_DIR="$BASE_DIR/pool-requests"
PROJECT_DIR="$BASE_DIR/project"
INVENTORY_DIR="$PR_DIR/knowledge"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}                    PIPELINE STATUS                             ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# 1. INVENTORY (fonctions à implémenter)
echo -e "${YELLOW}1. INVENTORY (fonctions restantes ❌)${NC}"
echo "   ───────────────────────────────────"
TOTAL_TODO=0
for inv in "$INVENTORY_DIR"/INVENTORY-*.md; do
    if [ -f "$inv" ]; then
        name=$(basename "$inv" .md | sed 's/INVENTORY-//')
        count=$(grep -c "❌" "$inv" 2>/dev/null || echo 0)
        printf "   %s: %3d  " "$name" "$count"
        TOTAL_TODO=$((TOTAL_TODO + count))
    fi
done
echo ""
if [ "$TOTAL_TODO" -eq 0 ]; then
    echo -e "   ${GREEN}✓ TOTAL: 0 - Coverage 100%${NC}"
else
    echo -e "   ${YELLOW}⚠ TOTAL: $TOTAL_TODO fonctions à implémenter${NC}"
fi
echo ""

# 2. PR-DOC (documentation à analyser)
echo -e "${YELLOW}2. PR-DOC (documentation à analyser)${NC}"
echo "   ───────────────────────────────────"
DOC_PENDING=$(ls "$PR_DIR"/pending/PR-DOC-*.md 2>/dev/null | wc -l | tr -d ' ')
DOC_ASSIGNED=$(ls "$PR_DIR"/assigned/PR-DOC-*.md 2>/dev/null | wc -l | tr -d ' ')
DOC_DONE=$(ls "$PR_DIR"/done/PR-DOC-*.md 2>/dev/null | wc -l | tr -d ' ')
printf "   Pending: %4d  Assigned: %4d  Done: %4d\n" "$DOC_PENDING" "$DOC_ASSIGNED" "$DOC_DONE"
echo ""

# 3. PR-SPEC (features à implémenter)
echo -e "${YELLOW}3. PR-SPEC (features à implémenter)${NC}"
echo "   ───────────────────────────────────"
SPEC_PENDING=$(ls "$PR_DIR"/pending/PR-SPEC-*.md 2>/dev/null | wc -l | tr -d ' ')
SPEC_ASSIGNED=$(ls "$PR_DIR"/assigned/PR-SPEC-*.md 2>/dev/null | wc -l | tr -d ' ')
SPEC_DONE=$(ls "$PR_DIR"/done/PR-SPEC-*.md 2>/dev/null | wc -l | tr -d ' ')
printf "   Pending: %4d  Assigned: %4d  Done: %4d\n" "$SPEC_PENDING" "$SPEC_ASSIGNED" "$SPEC_DONE"
echo ""

# 4. PR-TEST (tests à créer)
echo -e "${YELLOW}4. PR-TEST (tests à créer)${NC}"
echo "   ───────────────────────────────────"
TEST_PENDING=$(ls "$PR_DIR"/pending/PR-TEST-*.md 2>/dev/null | wc -l | tr -d ' ')
TEST_ASSIGNED=$(ls "$PR_DIR"/assigned/PR-TEST-*.md 2>/dev/null | wc -l | tr -d ' ')
TEST_DONE=$(ls "$PR_DIR"/done/PR-TEST-*.md 2>/dev/null | wc -l | tr -d ' ')
printf "   Pending: %4d  Assigned: %4d  Done: %4d\n" "$TEST_PENDING" "$TEST_ASSIGNED" "$TEST_DONE"
echo ""

# 5. PR-FIX (corrections)
echo -e "${YELLOW}5. PR-FIX (corrections)${NC}"
echo "   ───────────────────────────────────"
FIX_PENDING=$(ls "$PR_DIR"/pending/PR-FIX-*.md 2>/dev/null | wc -l | tr -d ' ')
FIX_ASSIGNED=$(ls "$PR_DIR"/assigned/PR-FIX-*.md 2>/dev/null | wc -l | tr -d ' ')
FIX_DONE=$(ls "$PR_DIR"/done/PR-FIX-*.md 2>/dev/null | wc -l | tr -d ' ')
printf "   Pending: %4d  Assigned: %4d  Done: %4d\n" "$FIX_PENDING" "$FIX_ASSIGNED" "$FIX_DONE"
echo ""

# 6. Fichiers de tests (si project/tests existe)
if [ -d "$PROJECT_DIR/tests" ]; then
    echo -e "${YELLOW}6. Fichiers de tests créés${NC}"
    echo "   ───────────────────────────────────"
    TEST_COUNT=$(ls "$PROJECT_DIR"/tests/test_*.py 2>/dev/null | wc -l | tr -d ' ')
    printf "   Total: %d fichiers test\n" "$TEST_COUNT"
    echo ""
fi

# 7. Réconciliation
echo -e "${YELLOW}7. Réconciliation${NC}"
echo "   ───────────────────────────────────"
TEST_PR_TOTAL=$((TEST_PENDING + TEST_ASSIGNED + TEST_DONE))

if [ "$SPEC_DONE" -gt "$TEST_PR_TOTAL" ]; then
    MISSING=$((SPEC_DONE - TEST_PR_TOTAL))
    echo -e "   ${RED}⚠ $MISSING PR-SPEC done sans PR-TEST${NC}"
else
    echo -e "   ${GREEN}✓ Tous les PR-SPEC done ont un PR-TEST${NC}"
fi
echo ""

# 8. Queues Redis
echo -e "${YELLOW}8. Queues Redis${NC}"
echo "   ───────────────────────────────────"
if command -v redis-cli &>/dev/null; then
    for q in 000 100 200 201 300 301 302 303 400 500 501 600; do
        len=$(redis-cli LLEN "ma:inject:$q" 2>/dev/null || echo 0)
        if [ "$len" -gt 0 ]; then
            if [ "$len" -gt 100 ]; then
                printf "   ${RED}%s: %4d${NC}\n" "$q" "$len"
            elif [ "$len" -gt 10 ]; then
                printf "   ${YELLOW}%s: %4d${NC}\n" "$q" "$len"
            else
                printf "   %s: %4d\n" "$q" "$len"
            fi
        fi
    done
else
    echo "   (redis-cli non disponible)"
fi
echo ""

echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
