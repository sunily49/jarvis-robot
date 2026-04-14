#!/bin/bash
# ══════════════════════════════════════════════════════════════════════
# JARVIS Robot — Raspberry Pi 5 Installation Script
# Usage: bash scripts/install_pi.sh [--skip-models]
# Safe to re-run (idempotent).
# ══════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ── Paths ─────────────────────────────────────────────────────────────
JARVIS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$JARVIS_DIR/venv"
DATA_DIR="$JARVIS_DIR/pi/data"
WAKEWORD_DIR="$HOME/wakeword_models"
PIPER_DIR="$HOME/piper_models"
SKIP_MODELS=false

# Parse args
for arg in "$@"; do
    case $arg in
        --skip-models) SKIP_MODELS=true ;;
    esac
done

step=0
total_steps=10

progress() {
    step=$((step + 1))
    echo -e "\n${BLUE}${BOLD}[$step/$total_steps]${NC} ${BOLD}$1${NC}"
}

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}○${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          JARVIS Robot — Pi 5 Installation               ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo "  Project dir: $JARVIS_DIR"
echo ""

# ══════════════════════════════════════════════════════════════════════
# PRE-FLIGHT CHECKS
# ══════════════════════════════════════════════════════════════════════

progress "Running pre-flight checks..."

# Check if running on a Pi
PREFLIGHT_OK=true

if [ -f /proc/device-tree/model ]; then
    PI_MODEL=$(cat /proc/device-tree/model | tr -d '\0')
    ok "Board: $PI_MODEL"
else
    warn "Not a Raspberry Pi (or /proc/device-tree/model missing) — proceeding anyway"
fi

# Check RAM
TOTAL_RAM_MB=$(free -m | awk '/Mem:/{print $2}')
if [ "$TOTAL_RAM_MB" -ge 4000 ]; then
    ok "RAM: ${TOTAL_RAM_MB}MB (recommended: 8GB)"
else
    warn "RAM: ${TOTAL_RAM_MB}MB — 4GB+ recommended for JARVIS"
fi

# Check OS
if [ -f /etc/os-release ]; then
    OS_NAME=$(grep PRETTY_NAME /etc/os-release | cut -d'"' -f2)
    ok "OS: $OS_NAME"
else
    warn "Could not determine OS"
fi

# Check architecture
ARCH=$(uname -m)
if [ "$ARCH" = "aarch64" ]; then
    ok "Architecture: 64-bit ($ARCH)"
else
    warn "Architecture: $ARCH — 64-bit recommended"
fi

# Check internet
if ping -c 1 -W 3 8.8.8.8 &>/dev/null; then
    ok "Internet: connected"
else
    fail "Internet: NOT connected — installation requires internet"
    exit 1
fi

# Check disk space
FREE_GB=$(df -BG / | awk 'NR==2{print $4}' | tr -d 'G')
if [ "$FREE_GB" -ge 5 ]; then
    ok "Disk: ${FREE_GB}GB free (need ~5GB)"
else
    fail "Disk: only ${FREE_GB}GB free — need at least 5GB"
    exit 1
fi

# Check user not root
if [ "$EUID" -eq 0 ]; then
    fail "Do not run as root. Run as your normal user (e.g., admin)"
    exit 1
fi
ok "User: $(whoami) (not root)"

# ══════════════════════════════════════════════════════════════════════
# SYSTEM PACKAGES
# ══════════════════════════════════════════════════════════════════════

progress "Installing system packages..."

sudo apt-get update -qq

# Core required packages
PACKAGES_REQUIRED=(
    python3-pip python3-venv python3-dev
    portaudio19-dev libportaudio2
    v4l-utils
    alsa-utils
    cmake build-essential
    git wget curl
    libffi-dev libssl-dev
)

# Optional packages — names vary by Debian/Ubuntu version; try each individually
PACKAGES_OPTIONAL=(
    "libopenblas-dev libatlas-base-dev"   # numpy BLAS: trixie uses libopenblas-dev; bookworm has both
    "python3-opencv"                      # system OpenCV (pip version used if missing)
    "i2c-tools"                           # I2C for PCA9685 servo board
    "mpv"                                 # Music playback (only needed if TOOL_MUSIC=true)
)

echo "  Installing required packages..."
sudo apt-get install -y "${PACKAGES_REQUIRED[@]}"
ok "Required system packages installed"

echo "  Installing optional packages (failures are non-fatal)..."
for pkg_group in "${PACKAGES_OPTIONAL[@]}"; do
    # Try each name in the group until one succeeds
    installed=false
    for pkg in $pkg_group; do
        if sudo apt-get install -y -q "$pkg" 2>/dev/null; then
            ok "  $pkg"
            installed=true
            break
        fi
    done
    if [ "$installed" = false ]; then
        warn "  ${pkg_group%% *} not available — skipping (non-fatal)"
    fi
done

# ══════════════════════════════════════════════════════════════════════
# PYTHON VIRTUAL ENVIRONMENT
# ══════════════════════════════════════════════════════════════════════

progress "Setting up Python virtual environment..."

if [ -d "$VENV_DIR" ]; then
    warn "Virtual environment exists — updating"
else
    python3 -m venv "$VENV_DIR"
    ok "Virtual environment created at $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip setuptools wheel -q
ok "pip/setuptools upgraded"

# Install requirements, skipping packages that fail (e.g. piper-tts on some ARM builds)
echo "  Installing Python dependencies (this may take a few minutes)..."
pip install -r "$JARVIS_DIR/pi/requirements.txt" --extra-index-url https://www.piwheels.org/simple/ 2>&1 \
    | grep -E "^(Successfully|ERROR|WARNING: Could not)" || true

# piper-tts: try piwheels arm64 wheel first, fall back gracefully
if ! python3 -c "import piper" 2>/dev/null; then
    pip install piper-tts --extra-index-url https://www.piwheels.org/simple/ -q 2>/dev/null \
        && ok "piper-tts installed" \
        || warn "piper-tts not available for this platform — TTS announcements will be skipped"
fi

# openwakeword: tflite-runtime doesn't support Python 3.12+; use onnxruntime backend instead
if ! python3 -c "import openwakeword" 2>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo "  Fixing openwakeword for Python $PY_VER (using onnxruntime backend)..."
    pip install onnxruntime -q --extra-index-url https://www.piwheels.org/simple/ 2>/dev/null \
        && pip install openwakeword --no-deps -q 2>/dev/null \
        && pip install scipy coloredlogs requests tqdm -q 2>/dev/null \
        && ok "openwakeword installed (onnxruntime backend)" \
        || warn "openwakeword install failed — TRIGGER_WAKEWORD will be set to false"
fi

# If openwakeword still not available, disable it in .env to prevent startup crash
if ! python3 -c "import openwakeword" 2>/dev/null; then
    if [ -f "$JARVIS_DIR/pi/.env" ]; then
        sed -i 's/^TRIGGER_WAKEWORD=true/TRIGGER_WAKEWORD=false/' "$JARVIS_DIR/pi/.env"
        warn "TRIGGER_WAKEWORD disabled in .env (openwakeword not available for Python $PY_VER)"
    fi
fi

ok "Python dependencies installed"

# Pi-specific GPIO packages (ignore errors on non-Pi)
pip install RPi.GPIO -q 2>/dev/null && ok "RPi.GPIO installed" || warn "RPi.GPIO skipped"
# gpiozero + lgpio: Pi 5 GPIO backend (RPi.GPIO doesn't support Pi 5)
pip install gpiozero lgpio -q 2>/dev/null && ok "gpiozero + lgpio installed (Pi 5 GPIO backend)" || warn "gpiozero skipped"
pip install adafruit-circuitpython-pca9685 adafruit-circuitpython-motor -q 2>/dev/null \
    && ok "Adafruit servo/motor libs installed" || warn "Adafruit libs skipped (enable HW_SERVOS to install later)"

# ══════════════════════════════════════════════════════════════════════
# DATA DIRECTORIES
# ══════════════════════════════════════════════════════════════════════

progress "Creating data directories..."

mkdir -p "$DATA_DIR"
mkdir -p "$WAKEWORD_DIR"
mkdir -p "$PIPER_DIR"
ok "Directories created"

# ══════════════════════════════════════════════════════════════════════
# USER GROUPS
# ══════════════════════════════════════════════════════════════════════

progress "Checking user group memberships..."

REQUIRED_GROUPS="gpio video audio i2c spi"
MISSING_GROUPS=""
for g in $REQUIRED_GROUPS; do
    if getent group "$g" &>/dev/null; then
        if id -nG "$USER" | grep -qw "$g"; then
            ok "User in group: $g"
        else
            sudo usermod -aG "$g" "$USER" 2>/dev/null || true
            MISSING_GROUPS="$MISSING_GROUPS $g"
            warn "Added user to group: $g (re-login required)"
        fi
    fi
done

if [ -n "$MISSING_GROUPS" ]; then
    warn "You were added to groups:$MISSING_GROUPS — log out and back in for this to take effect"
fi

# ══════════════════════════════════════════════════════════════════════
# AUDIO CONFIGURATION
# ══════════════════════════════════════════════════════════════════════

progress "Configuring audio..."

# List audio devices
echo "  Audio input devices:"
if command -v arecord &>/dev/null; then
    arecord -l 2>/dev/null | grep "^card" | while read -r line; do
        echo "    $line"
    done
fi

echo "  Audio output devices:"
if command -v aplay &>/dev/null; then
    aplay -l 2>/dev/null | grep "^card" | while read -r line; do
        echo "    $line"
    done
fi

# Auto-detect audio devices:
#   MIC_CARD  — prefer EMEET PIXY (camera mic), fall back to any USB input
#   SPK_CARD  — prefer USB device with playback (not HDMI), fall back to MIC_CARD
MIC_CARD=$(arecord -l 2>/dev/null | grep -i -m1 "EMEET\|PIXY" | awk -F'[: ]' '{print $2}')
if [ -z "$MIC_CARD" ]; then
    MIC_CARD=$(arecord -l 2>/dev/null | grep -i -m1 "USB" | awk -F'[: ]' '{print $2}')
fi

# Speaker: USB device with playback that is NOT HDMI
SPK_CARD=$(aplay -l 2>/dev/null | grep -i "USB" | grep -iv "hdmi" | awk -F'[: ]' '{print $2}' | head -1)
if [ -z "$SPK_CARD" ]; then
    SPK_CARD="$MIC_CARD"  # fallback: same device for both
fi

if [ -n "$MIC_CARD" ]; then
    ok "Mic device: card $MIC_CARD  |  Speaker device: card $SPK_CARD"

    ASOUND_CONF="$HOME/.asoundrc"
    if [ ! -f "$ASOUND_CONF" ]; then
        cat > "$ASOUND_CONF" << EOF
# JARVIS ALSA config — split mic/speaker
pcm.!default {
    type asym
    playback.pcm "plughw:${SPK_CARD},0"
    capture.pcm  "plughw:${MIC_CARD},0"
}
ctl.!default {
    type hw
    card ${SPK_CARD}
}
EOF
        ok "ALSA config written to $ASOUND_CONF (mic=card${MIC_CARD}, spk=card${SPK_CARD})"
    else
        warn "ALSA config exists at $ASOUND_CONF — not overwriting"
        warn "To update: remove $ASOUND_CONF and re-run make install"
    fi
else
    warn "No USB audio device detected — configure AUDIO_DEVICE_INDEX manually in .env"
fi

# Write detected device indices into .env for PyAudio
if [ -n "$MIC_CARD" ] && [ -f "$JARVIS_DIR/pi/.env" ]; then
    # PyAudio enumerates devices differently; -1 = auto-detect (PyAudio picks first available)
    # User can override with make config if needed
    sed -i "s/^AUDIO_DEVICE_INDEX=.*/AUDIO_DEVICE_INDEX=-1/" "$JARVIS_DIR/pi/.env" 2>/dev/null || true
fi

# ══════════════════════════════════════════════════════════════════════
# CAMERA CHECK
# ══════════════════════════════════════════════════════════════════════

progress "Checking camera..."

if [ -e /dev/video0 ]; then
    ok "Camera device found at /dev/video0"
    v4l2-ctl -d /dev/video0 --info 2>/dev/null | head -3 | while read -r line; do
        echo "    $line"
    done
elif [ -e /dev/video2 ]; then
    warn "Camera at /dev/video2 (not /dev/video0) — update CAMERA_DEVICE in .env"
else
    warn "No camera device found — plug in USB camera and reboot"
fi

# ══════════════════════════════════════════════════════════════════════
# MODEL DOWNLOADS
# ══════════════════════════════════════════════════════════════════════

if [ "$SKIP_MODELS" = true ]; then
    progress "Skipping model downloads (--skip-models)"
else
    progress "Downloading AI models..."

    # Wake word model — download hey_jarvis directly from openWakeWord releases
    if [ ! -f "$WAKEWORD_DIR/hey_jarvis.onnx" ]; then
        echo "  Downloading hey_jarvis wake word model..."
        # Try direct GitHub release first
        wget -q --show-progress \
            -O "$WAKEWORD_DIR/hey_jarvis.onnx" \
            "https://github.com/dscripka/openWakeWord/releases/download/v0.1.1/hey_jarvis_v0.1.onnx" \
            2>/dev/null \
        || {
            # Fallback: copy from installed openwakeword package resources
            OWW_MODELS=$("$VENV_DIR/bin/python3" -c \
                "import openwakeword, os; print(os.path.join(os.path.dirname(openwakeword.__file__), 'resources', 'models'))" \
                2>/dev/null)
            if [ -n "$OWW_MODELS" ]; then
                MODEL_FILE=$(find "$OWW_MODELS" -name "*hey_jarvis*" -o -name "*jarvis*" 2>/dev/null | head -1)
                if [ -n "$MODEL_FILE" ]; then
                    cp "$MODEL_FILE" "$WAKEWORD_DIR/hey_jarvis.onnx"
                    ok "hey_jarvis model copied from package: $MODEL_FILE"
                else
                    warn "hey_jarvis model not found — add $WAKEWORD_DIR/hey_jarvis.onnx manually"
                fi
            else
                warn "Wake word model download failed — add $WAKEWORD_DIR/hey_jarvis.onnx manually"
            fi
        }
        [ -f "$WAKEWORD_DIR/hey_jarvis.onnx" ] && ok "Wake word model ready at $WAKEWORD_DIR/hey_jarvis.onnx"
    else
        ok "Wake word model already exists"
    fi

    # Piper TTS model
    if [ ! -f "$PIPER_DIR/en_US-lessac-medium.onnx" ]; then
        echo "  Downloading Piper TTS voice model..."
        PIPER_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
        wget -q --show-progress -O "$PIPER_DIR/en_US-lessac-medium.onnx" "$PIPER_BASE/en_US-lessac-medium.onnx" || warn "Piper model download failed"
        wget -q -O "$PIPER_DIR/en_US-lessac-medium.onnx.json" "$PIPER_BASE/en_US-lessac-medium.onnx.json" 2>/dev/null || true
        ok "Piper TTS model downloaded"
    else
        ok "Piper TTS model already exists"
    fi
fi

# ══════════════════════════════════════════════════════════════════════
# ENVIRONMENT CONFIG
# ══════════════════════════════════════════════════════════════════════

progress "Setting up configuration..."

if [ ! -f "$JARVIS_DIR/pi/.env" ]; then
    cp "$JARVIS_DIR/pi/.env.example" "$JARVIS_DIR/pi/.env"
    ok "Created .env from template"
    echo ""
    echo -e "  ${YELLOW}${BOLD}ACTION REQUIRED:${NC} Edit your .env file:"
    echo -e "  ${BOLD}nano $JARVIS_DIR/pi/.env${NC}"
    echo ""
    echo "  At minimum, set:"
    echo "    GEMINI_API_KEY=your_key_here"
    echo ""
else
    ok ".env already exists"

    # Check if API key is set
    if grep -q "your_gemini_api_key_here" "$JARVIS_DIR/pi/.env" 2>/dev/null; then
        warn "GEMINI_API_KEY is still the placeholder — edit .env before starting!"
    else
        ok "GEMINI_API_KEY appears to be set"
    fi
fi

# ══════════════════════════════════════════════════════════════════════
# SYSTEMD SERVICE
# ══════════════════════════════════════════════════════════════════════

progress "Installing systemd service..."

# Update paths in service file to match actual install location
SERVICE_FILE="/etc/systemd/system/jarvis.service"

sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=JARVIS Robot AI Assistant
After=network-online.target sound.target graphical.target
Wants=network-online.target graphical.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$JARVIS_DIR/pi
ExecStart=$VENV_DIR/bin/python -m jarvis.main
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment="PYTHONUNBUFFERED=1"
Environment="DISPLAY=:0"
Environment="XAUTHORITY=/home/$USER/.Xauthority"
EnvironmentFile=$JARVIS_DIR/pi/.env

# Resource limits
MemoryMax=2G
CPUQuota=85%

# Security
PrivateTmp=true

# Allow GPIO and device access
SupplementaryGroups=gpio video audio i2c spi

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable jarvis.service 2>/dev/null
ok "Service installed and enabled"

# ── Logrotate ─────────────────────────────────────────────────────────
if [ -f "$JARVIS_DIR/pi/deploy/jarvis-logrotate.conf" ]; then
    sudo cp "$JARVIS_DIR/pi/deploy/jarvis-logrotate.conf" /etc/logrotate.d/jarvis 2>/dev/null || true
    ok "Log rotation configured"
fi

# ══════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════

echo ""
echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║              Installation Complete!                     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  ${BOLD}Next steps:${NC}"
echo ""
echo -e "  1. ${BOLD}Configure:${NC}    nano $JARVIS_DIR/pi/.env"
echo -e "  2. ${BOLD}Test hardware:${NC} make hw-test"
echo -e "  3. ${BOLD}Manual run:${NC}   cd $JARVIS_DIR/pi && source ../venv/bin/activate && python -m jarvis.main"
echo -e "  4. ${BOLD}Start service:${NC} sudo systemctl start jarvis"
echo -e "  5. ${BOLD}View logs:${NC}    journalctl -u jarvis -f"
echo ""
echo -e "  ${BOLD}Quick commands:${NC}  make start | make stop | make logs | make status | make health"
echo ""

if [ -n "$MISSING_GROUPS" ]; then
    echo -e "  ${YELLOW}⚠ You were added to new groups — log out and back in first!${NC}"
    echo ""
fi
