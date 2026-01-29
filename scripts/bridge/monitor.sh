#!/bin/bash
# monitor.sh - Affiche l'état des agents en temps réel (Redis Streams version)
# Usage: ./monitor.sh [interval_seconds]

INTERVAL=${1:-2}
REDIS_CLI="redis-cli"

clear
echo "Multi-Agent Bridge Monitor (refresh: ${INTERVAL}s, Ctrl+C to quit)"
echo ""

while true; do
    # Retour en haut
    tput cup 2 0

    echo "+--------+----------+--------+-------+----------+---------+------------------+"
    echo "| ID     | Status   | Queue  | Tasks | Session  | Age     | Current Task     |"
    echo "+--------+----------+--------+-------+----------+---------+------------------+"

    # Récupérer tous les agents (nouveau format ma:agent:XXX)
    for key in $($REDIS_CLI KEYS "ma:agent:*" 2>/dev/null | grep -E "^ma:agent:[0-9]+$" | sort -t: -k3 -n); do
        agent_id=$(echo "$key" | cut -d: -f3)

        status=$($REDIS_CLI HGET "$key" status 2>/dev/null || echo "?")
        queue=$($REDIS_CLI HGET "$key" queue_size 2>/dev/null || echo "?")
        tasks=$($REDIS_CLI HGET "$key" tasks_completed 2>/dev/null || echo "0")
        session=$($REDIS_CLI HGET "$key" session_id 2>/dev/null || echo "-")
        task_from=$($REDIS_CLI HGET "$key" current_task_from 2>/dev/null || echo "")
        last_seen=$($REDIS_CLI HGET "$key" last_seen 2>/dev/null || echo "0")

        # Calculer âge
        if [ "$last_seen" != "0" ] && [ "$last_seen" != "" ]; then
            now=$(date +%s)
            age=$((now - last_seen))
            if [ $age -lt 60 ]; then
                age_str="${age}s ago"
            else
                age_str="$((age / 60))m ago"
            fi
        else
            age_str="unknown"
        fi

        # Couleur status
        case "$status" in
            idle)    status_col="\033[32m$status\033[0m"   ;;  # vert
            busy)    status_col="\033[33m$status\033[0m"   ;;  # jaune
            stopped) status_col="\033[31m$status\033[0m"   ;;  # rouge
            *)       status_col="\033[31m$status\033[0m"   ;;  # rouge
        esac

        # Truncate session
        session="${session:0:8}"

        printf "| %-6s | %-16b | %-6s | %-5s | %-8s | %-7s | %-16s |\n" \
            "$agent_id" "$status_col" "$queue" "$tasks" "$session" "$age_str" "${task_from:--}"
    done

    echo "+--------+----------+--------+-------+----------+---------+------------------+"
    echo ""

    # Stream stats
    echo "Redis Streams:"
    for stream in $($REDIS_CLI KEYS "ma:agent:*:inbox" 2>/dev/null | head -10); do
        len=$($REDIS_CLI XLEN "$stream" 2>/dev/null || echo 0)
        if [ "$len" -gt 0 ]; then
            echo "  $stream: $len messages"
        fi
    done

    echo ""
    echo "Tmux sessions:"
    tmux ls 2>/dev/null | grep "^agent-" | head -10 || echo "  (none)"

    # Clear reste de l'écran
    tput ed

    sleep "$INTERVAL"
done
