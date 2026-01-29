#!/bin/bash
# monitor-all.sh - Monitor ALL agent communications in real-time
# Usage: ./monitor-all.sh

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║           MULTI-AGENT MONITOR (all streams)                ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Watching all ma:agent:*:inbox and ma:agent:*:outbox streams${NC}"
echo -e "${YELLOW}Press Ctrl+C to quit${NC}"
echo ""

# Get all agent streams
get_streams() {
    redis-cli KEYS "ma:agent:*:inbox" "ma:agent:*:outbox" 2>/dev/null | sort
}

# Track last IDs per stream
declare -A LAST_IDS

# Initialize last IDs to current position
for stream in $(get_streams); do
    LAST_IDS["$stream"]='$'
done

format_time() {
    date '+%H:%M:%S'
}

# Color based on agent type
agent_color() {
    local id=$1
    case ${id:0:1} in
        0) echo -e "${MAGENTA}" ;;  # Super-Master
        1) echo -e "${CYAN}" ;;     # Master
        2) echo -e "${BLUE}" ;;     # Explorer
        3) echo -e "${GREEN}" ;;    # Developer
        4) echo -e "${YELLOW}" ;;   # Integrator
        5) echo -e "${RED}" ;;      # Tester
        6) echo -e "${MAGENTA}" ;;  # Releaser
        9) echo -e "${RED}" ;;      # Architect
        *) echo -e "${NC}" ;;
    esac
}

while true; do
    # Refresh stream list periodically
    STREAMS=$(get_streams)

    for stream in $STREAMS; do
        LAST_ID="${LAST_IDS[$stream]:-\$}"

        # Read new messages
        RESULT=$(redis-cli XREAD COUNT 10 STREAMS "$stream" "$LAST_ID" 2>/dev/null)

        if [ -n "$RESULT" ]; then
            # Parse stream name to get agent ID and direction
            # Format: ma:agent:300:inbox or ma:agent:300:outbox
            AGENT_ID=$(echo "$stream" | cut -d: -f3)
            DIRECTION=$(echo "$stream" | cut -d: -f4)

            COLOR=$(agent_color "$AGENT_ID")

            # Extract message IDs and content
            echo "$RESULT" | while IFS= read -r line; do
                # Look for message IDs (format: 1234567890123-0)
                if [[ "$line" =~ ([0-9]+-[0-9]+) ]]; then
                    MSG_ID="${BASH_REMATCH[1]}"
                    LAST_IDS["$stream"]="$MSG_ID"

                    # Extract key fields
                    PROMPT=$(echo "$RESULT" | grep -oP 'prompt[^"]*"[^"]*"' | head -1 | sed 's/prompt[^"]*"//' | tr -d '"' | head -c 80)
                    RESPONSE=$(echo "$RESULT" | grep -oP 'response[^"]*"[^"]*"' | head -1 | sed 's/response[^"]*"//' | tr -d '"' | head -c 80)
                    FROM=$(echo "$RESULT" | grep -oP 'from_agent[^"]*"[^"]*"' | head -1 | sed 's/from_agent[^"]*"//' | tr -d '"')
                    TO=$(echo "$RESULT" | grep -oP 'to_agent[^"]*"[^"]*"' | head -1 | sed 's/to_agent[^"]*"//' | tr -d '"')
                    TYPE=$(echo "$RESULT" | grep -oP 'type[^"]*"[^"]*"' | head -1 | sed 's/type[^"]*"//' | tr -d '"')

                    # Format output
                    TIME=$(format_time)

                    if [ "$DIRECTION" = "inbox" ]; then
                        ARROW="→"
                        if [ -n "$PROMPT" ]; then
                            echo -e "${COLOR}[$TIME] ${ARROW} [$AGENT_ID] ${NC}from:${FROM:-?} ${YELLOW}\"${PROMPT}...\"${NC}"
                        elif [ -n "$RESPONSE" ]; then
                            echo -e "${COLOR}[$TIME] ${ARROW} [$AGENT_ID] ${NC}response from:${FROM:-?} (${#RESPONSE} chars)"
                        fi
                    else
                        ARROW="←"
                        if [ -n "$RESPONSE" ]; then
                            echo -e "${COLOR}[$TIME] ${ARROW} [$AGENT_ID] ${NC}to:${TO:-broadcast} ${GREEN}\"${RESPONSE}...\"${NC}"
                        fi
                    fi
                fi
            done
        fi
    done

    sleep 0.5
done
