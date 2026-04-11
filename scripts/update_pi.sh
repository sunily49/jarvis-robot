#!/bin/bash
# ══════════════════════════════════════════════════════════════════════
# JARVIS OTA Update — pull latest code, update deps, restart service
# Auto-rollback on failure.
# ══════════════════════════════════════════════════════════════════════

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

JARVIS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$JARVIS_DIR/venv"

echo -e "${BOLD}JARVIS OTA Update${NC}"
echo "──────────────────────────────────────────"

cd "$JARVIS_DIR"

# ── Save rollback point ──────────────────────────────────────────────
PREV_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "none")
echo -e "  Current commit: ${PREV_COMMIT:0:8}"

# ── Pull latest ──────────────────────────────────────────────────────
echo -e "  Pulling latest changes..."
if git pull --ff-only 2>/dev/null; then
    NEW_COMMIT=$(git rev-parse HEAD)
    if [ "$PREV_COMMIT" = "$NEW_COMMIT" ]; then
        echo -e "  ${GREEN}✓${NC} Already up to date"
    else
        echo -e "  ${GREEN}✓${NC} Updated to ${NEW_COMMIT:0:8}"
        git log --oneline "${PREV_COMMIT}..HEAD" | head -10 | while read -r line; do
            echo "    $line"
        done
    fi
else
    echo -e "  ${YELLOW}○${NC} Fast-forward failed — trying merge..."
    git pull || {
        echo -e "  ${RED}✗${NC} Git pull failed. Resolve conflicts manually."
        exit 1
    }
fi

# ── Update dependencies ──────────────────────────────────────────────
echo -e "  Updating Python dependencies..."
source "$VENV_DIR/bin/activate"
pip install -r "$JARVIS_DIR/pi/requirements.txt" -q 2>/dev/null
echo -e "  ${GREEN}✓${NC} Dependencies updated"

# ── Restart service ──────────────────────────────────────────────────
echo -e "  Restarting JARVIS service..."
sudo systemctl restart jarvis

# ── Verify startup ───────────────────────────────────────────────────
echo -e "  Waiting for startup (max 30s)..."
for i in $(seq 1 30); do
    if systemctl is-active --quiet jarvis 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} JARVIS is running (started in ${i}s)"
        echo ""
        echo -e "${GREEN}${BOLD}Update successful!${NC}"
        exit 0
    fi
    sleep 1
done

# ── Startup failed — rollback ────────────────────────────────────────
echo -e "  ${RED}✗${NC} JARVIS failed to start within 30s"
echo ""

if [ "$PREV_COMMIT" != "none" ]; then
    echo -e "  ${YELLOW}Rolling back to ${PREV_COMMIT:0:8}...${NC}"
    git checkout "$PREV_COMMIT"
    sudo systemctl restart jarvis
    sleep 5

    if systemctl is-active --quiet jarvis 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} Rollback successful — running on ${PREV_COMMIT:0:8}"
    else
        echo -e "  ${RED}✗${NC} Rollback also failed — check: journalctl -u jarvis -n 50"
    fi
else
    echo -e "  ${RED}No previous commit to rollback to${NC}"
fi

echo ""
echo "  Check logs: journalctl -u jarvis -n 50 --no-pager"
exit 1
