#!/bin/bash
#
# Watch all agents in real-time
#
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS_DIR="$SCRIPT_DIR/../logs"

# Reset color
NC="\033[0m"

# Function to get color for agent
get_color() {
    case $1 in
        000) echo "\033[1;97m" ;;  # White - Mini Super-Master
        100) echo "\033[1;33m" ;;  # Yellow - Master
        200) echo "\033[1;36m" ;;  # Cyan - Explorer
        201) echo "\033[1;96m" ;;  # Light Cyan - Doc Explorer
        300) echo "\033[1;32m" ;;  # Green - Dev Excel
        301) echo "\033[1;32m" ;;  # Green - Dev Word
        302) echo "\033[1;32m" ;;  # Green - Dev PPTX
        303) echo "\033[1;32m" ;;  # Green - Dev PDF
        400) echo "\033[1;35m" ;;  # Magenta - Merge
        500) echo "\033[1;34m" ;;  # Blue - Test
        501) echo "\033[1;94m" ;;  # Light Blue - Test Creator
        600) echo "\033[1;31m" ;;  # Red - Release
        *) echo "$NC" ;;
    esac
}

echo "═══════════════════════════════════════════════════"
echo "         WATCHING ALL AGENTS (Ctrl+C to stop)"
echo "═══════════════════════════════════════════════════"
echo ""

# Tail all logs with agent prefix
tail -F "$LOGS_DIR"/*/claude.log 2>/dev/null | while read line; do
    # Extract agent ID from path
    if [[ "$line" =~ ^\=\=\>.*logs/([0-9]+)/claude\.log ]]; then
        CURRENT_AGENT="${BASH_REMATCH[1]}"
        continue
    fi

    # Skip empty lines and prompt dumps
    [[ -z "$line" ]] && continue
    [[ "$line" =~ ^#.*Agent ]] && continue
    [[ "$line" =~ ^\-\-\-$ ]] && continue

    # Show RESPONSE lines with color
    if [[ "$line" =~ RESPONSE: ]] || [[ "$line" =~ ^000 ]] || [[ "$line" =~ ^Master ]] || [[ "$line" =~ ^Explorer ]] || [[ "$line" =~ ^Dev ]] || [[ "$line" =~ ^Merge ]] || [[ "$line" =~ ^Test ]] || [[ "$line" =~ ^Release ]] || [[ "$line" =~ ^Doc ]]; then
        COLOR=$(get_color "$CURRENT_AGENT")
        echo -e "${COLOR}[$CURRENT_AGENT]${NC} $line"
    fi
done
