#!/bin/bash
# ══════════════════════════════════════════════════════════════════════
# JARVIS Server — Home Server Installation Script
# Run as: bash scripts/install_server.sh
# ══════════════════════════════════════════════════════════════════════

set -e

SERVER_DIR="$HOME/jarvis-server"
VENV_DIR="$SERVER_DIR/venv"

echo "================================================"
echo "  JARVIS Server — Installation"
echo "================================================"

# ── System dependencies ───────────────────────────────────────────────
echo "[1/5] Installing system packages..."
sudo apt-get update
sudo apt-get install -y \
    python3-pip python3-venv python3-dev \
    libopencv-dev \
    cmake build-essential \
    git

# ── Copy server files ────────────────────────────────────────────────
echo "[2/5] Setting up server directory..."
mkdir -p "$SERVER_DIR/data"

# Copy from project (assumes git clone already done)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cp -r "$PROJECT_DIR/server/"* "$SERVER_DIR/"

# ── Python virtual environment ────────────────────────────────────────
echo "[3/5] Setting up Python virtual environment..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

pip install --upgrade pip setuptools wheel
pip install -r "$SERVER_DIR/requirements.txt"

# ── Install Ollama ────────────────────────────────────────────────────
echo "[4/5] Installing Ollama..."
if ! command -v ollama &> /dev/null; then
    curl -fsSL https://ollama.ai/install.sh | sh
    echo "Pulling mistral model (this may take a while)..."
    ollama pull mistral
else
    echo "Ollama already installed"
fi

# ── Install systemd service ───────────────────────────────────────────
echo "[5/5] Installing systemd service..."
sudo cp "$SERVER_DIR/deploy/jarvis-server.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable jarvis-server.service
echo "Service installed."

echo ""
echo "================================================"
echo "  Server installation complete!"
echo "================================================"
echo ""
echo "Next steps:"
echo "  1. Start server:  sudo systemctl start jarvis-server"
echo "  2. View logs:     journalctl -u jarvis-server -f"
echo "  3. Test health:   curl http://localhost:9000/health"
echo ""
echo "The Pi will auto-discover this server via mDNS."
echo "Fallback: set SERVER_HOST in Pi's .env to this machine's IP."
