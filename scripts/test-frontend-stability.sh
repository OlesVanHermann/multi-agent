#!/bin/bash
# Test frontend stability for 2 hours
# Check every 5 minutes

FRONTEND_URL="http://127.0.0.1:8000"
INTERVAL=300  # 5 minutes
ITERATIONS=24  # 2 hours (24 * 5min = 120min)
LOG_FILE="$HOME/multi-agent/logs/000/frontend-stability-$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$(dirname "$LOG_FILE")"

echo "=== Frontend Stability Test ===" | tee -a "$LOG_FILE"
echo "Start: $(date)" | tee -a "$LOG_FILE"
echo "Duration: 2 hours (24 checks, every 5 min)" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

for i in $(seq 1 $ITERATIONS); do
    echo "[Check $i/$ITERATIONS] $(date +%H:%M:%S)" | tee -a "$LOG_FILE"

    # Test 1: HTTP GET
    if curl -sf "$FRONTEND_URL" > /dev/null 2>&1; then
        echo "  ✓ HTTP GET OK" | tee -a "$LOG_FILE"
    else
        echo "  ✗ HTTP GET FAILED" | tee -a "$LOG_FILE"
    fi

    # Test 2: API endpoint
    if curl -sf "$FRONTEND_URL/api/agents" > /dev/null 2>&1; then
        echo "  ✓ API OK" | tee -a "$LOG_FILE"
    else
        echo "  ✗ API FAILED" | tee -a "$LOG_FILE"
    fi

    # Test 3: Response time
    response_time=$(curl -sf -o /dev/null -w '%{time_total}' "$FRONTEND_URL" 2>/dev/null || echo "0")
    echo "  ⏱ Response time: ${response_time}s" | tee -a "$LOG_FILE"

    # Test 4: Process check
    if pgrep -f "uvicorn server:app" > /dev/null; then
        echo "  ✓ Process running" | tee -a "$LOG_FILE"
    else
        echo "  ✗ Process NOT running" | tee -a "$LOG_FILE"
    fi

    echo "" | tee -a "$LOG_FILE"

    # Wait before next check (except last iteration)
    if [ $i -lt $ITERATIONS ]; then
        sleep $INTERVAL
    fi
done

echo "=== Test Complete ===" | tee -a "$LOG_FILE"
echo "End: $(date)" | tee -a "$LOG_FILE"
echo "Log: $LOG_FILE" | tee -a "$LOG_FILE"
