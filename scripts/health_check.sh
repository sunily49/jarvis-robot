#!/bin/bash
# ══════════════════════════════════════════════════════════════════════
# JARVIS Health Check — watchdog script for monitoring
# Usage: bash scripts/health_check.sh [--quiet]
# Can be called by cron every 5 minutes.
# ══════════════════════════════════════════════════════════════════════

QUIET=false
for arg in "$@"; do
    [ "$arg" = "--quiet" ] && QUIET=true
done

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { [ "$QUIET" = true ] && echo "OK: $1" || echo -e "  ${GREEN}✓${NC} $1"; }
warn() { [ "$QUIET" = true ] && echo "WARN: $1" || echo -e "  ${YELLOW}○${NC} $1"; }
fail() { [ "$QUIET" = true ] && echo "FAIL: $1" || echo -e "  ${RED}✗${NC} $1"; }

passed=0
total=0
check() { total=$((total + 1)); }

NOW=$(date '+%Y-%m-%d %H:%M:%S')

if [ "$QUIET" = false ]; then
    echo -e "${BOLD}JARVIS Health Check — $NOW${NC}"
    echo "──────────────────────────────────────────"
fi

# ── Service Status ────────────────────────────────────────────────────
check
if systemctl is-active --quiet jarvis 2>/dev/null; then
    PID=$(systemctl show jarvis -p MainPID --value 2>/dev/null)
    UPTIME=$(ps -o etime= -p "$PID" 2>/dev/null | xargs)
    ok "Service:     running (pid $PID, uptime $UPTIME)"
    passed=$((passed + 1))
else
    STATE=$(systemctl is-active jarvis 2>/dev/null || echo "not found")
    fail "Service:     $STATE"
fi

# ── CPU Usage ─────────────────────────────────────────────────────────
check
CPU=$(top -bn1 | grep "Cpu(s)" | awk '{print 100 - $8}' | cut -d. -f1 2>/dev/null || echo "?")
if [ "$CPU" != "?" ] && [ "$CPU" -lt 85 ]; then
    ok "CPU:         ${CPU}% (limit: 85%)"
    passed=$((passed + 1))
elif [ "$CPU" != "?" ]; then
    warn "CPU:         ${CPU}% — HIGH (limit: 85%)"
    passed=$((passed + 1))
else
    warn "CPU:         could not measure"
fi

# ── Memory Usage ──────────────────────────────────────────────────────
check
MEM_USED=$(free -m | awk '/Mem:/{print $3}')
MEM_TOTAL=$(free -m | awk '/Mem:/{print $2}')
MEM_PCT=$((MEM_USED * 100 / MEM_TOTAL))
if [ "$MEM_PCT" -lt 80 ]; then
    ok "Memory:      ${MEM_USED}M / ${MEM_TOTAL}M (${MEM_PCT}%)"
    passed=$((passed + 1))
else
    warn "Memory:      ${MEM_USED}M / ${MEM_TOTAL}M (${MEM_PCT}%) — HIGH"
fi

# ── Temperature ───────────────────────────────────────────────────────
check
if command -v vcgencmd &>/dev/null; then
    TEMP=$(vcgencmd measure_temp 2>/dev/null | grep -oP '[0-9.]+')
    TEMP_INT=${TEMP%.*}
    if [ -n "$TEMP_INT" ] && [ "$TEMP_INT" -lt 70 ]; then
        ok "Temperature: ${TEMP}°C (throttle at 80°C)"
        passed=$((passed + 1))
    elif [ -n "$TEMP_INT" ] && [ "$TEMP_INT" -lt 80 ]; then
        warn "Temperature: ${TEMP}°C — WARM (throttle at 80°C)"
        passed=$((passed + 1))
    elif [ -n "$TEMP_INT" ]; then
        fail "Temperature: ${TEMP}°C — THROTTLING"
    else
        warn "Temperature: could not read"
    fi
else
    # Try thermal zone
    if [ -f /sys/class/thermal/thermal_zone0/temp ]; then
        TEMP_RAW=$(cat /sys/class/thermal/thermal_zone0/temp)
        TEMP=$((TEMP_RAW / 1000))
        if [ "$TEMP" -lt 70 ]; then
            ok "Temperature: ${TEMP}°C"
            passed=$((passed + 1))
        else
            warn "Temperature: ${TEMP}°C — HIGH"
        fi
    else
        warn "Temperature: not available"
    fi
fi

# ── Disk Space ────────────────────────────────────────────────────────
check
DISK_FREE=$(df -BG / | awk 'NR==2{print $4}' | tr -d 'G')
DISK_PCT=$(df / | awk 'NR==2{print $5}' | tr -d '%')
if [ "$DISK_PCT" -lt 90 ]; then
    ok "Disk:        ${DISK_FREE}GB free (${DISK_PCT}% used)"
    passed=$((passed + 1))
else
    warn "Disk:        ${DISK_FREE}GB free (${DISK_PCT}% used) — LOW"
fi

# ── Camera ────────────────────────────────────────────────────────────
check
if [ -e /dev/video0 ]; then
    ok "Camera:      /dev/video0 available"
    passed=$((passed + 1))
elif [ -e /dev/video2 ]; then
    warn "Camera:      /dev/video2 (not video0)"
    passed=$((passed + 1))
else
    fail "Camera:      no video device found"
fi

# ── Network ───────────────────────────────────────────────────────────
check
if ping -c 1 -W 3 8.8.8.8 &>/dev/null; then
    ok "Network:     internet OK"
    passed=$((passed + 1))
else
    fail "Network:     no internet"
fi

# ── Gemini API ────────────────────────────────────────────────────────
check
JARVIS_DIR="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)"
ENV_FILE="$JARVIS_DIR/pi/.env"
if [ -f "$ENV_FILE" ]; then
    API_KEY=$(grep "^GEMINI_API_KEY=" "$ENV_FILE" 2>/dev/null | cut -d= -f2)
    if [ -n "$API_KEY" ] && [ "$API_KEY" != "your_gemini_api_key_here" ]; then
        # Quick reachability check (DNS only, don't burn API quota)
        if ping -c 1 -W 3 generativelanguage.googleapis.com &>/dev/null; then
            ok "Gemini API:  reachable (key configured)"
            passed=$((passed + 1))
        else
            warn "Gemini API:  DNS unreachable (key configured)"
        fi
    else
        fail "Gemini API:  key not configured in .env"
    fi
else
    fail "Gemini API:  .env file not found"
fi

# ── Server ────────────────────────────────────────────────────────────
check
if [ -f "$ENV_FILE" ]; then
    SERVER_ENABLED=$(grep "^SERVER_ENABLED=" "$ENV_FILE" 2>/dev/null | cut -d= -f2)
    if [ "$SERVER_ENABLED" = "true" ]; then
        SERVER_HOST=$(grep "^SERVER_HOST=" "$ENV_FILE" | cut -d= -f2)
        SERVER_PORT=$(grep "^SERVER_PORT=" "$ENV_FILE" | cut -d= -f2)
        if curl -s --max-time 3 "http://${SERVER_HOST}:${SERVER_PORT}/health" &>/dev/null; then
            ok "Server:      online at ${SERVER_HOST}:${SERVER_PORT}"
            passed=$((passed + 1))
        else
            warn "Server:      offline (degraded mode OK)"
            passed=$((passed + 1))  # Offline is acceptable
        fi
    else
        warn "Server:      disabled"
        passed=$((passed + 1))
    fi
else
    warn "Server:      .env not found"
fi

# ── Summary ───────────────────────────────────────────────────────────
if [ "$QUIET" = false ]; then
    echo "──────────────────────────────────────────"
    if [ "$passed" -eq "$total" ]; then
        echo -e "  ${GREEN}${BOLD}Status: HEALTHY ($passed/$total)${NC}"
    elif [ "$passed" -ge $((total - 2)) ]; then
        echo -e "  ${YELLOW}${BOLD}Status: DEGRADED ($passed/$total)${NC}"
    else
        echo -e "  ${RED}${BOLD}Status: UNHEALTHY ($passed/$total)${NC}"
    fi
else
    echo "HEALTH: $passed/$total at $NOW"
fi

exit $(( total - passed ))
