"""
JARVIS Configuration — loads all settings from .env with sensible defaults.
Every trigger, tool, and feature is gated by a boolean flag.

Network modes (selected automatically by NetworkMonitor):
  FULL_CLOUD   — WiFi + internet → Gemini Live (primary)
  LOCAL_SERVER — WiFi only       → Ollama via server or Pi-local
  OFFLINE      — No network      → local Ollama + Piper TTS only
"""

import os
from pathlib import Path
from dotenv import load_dotenv

_HOME = Path.home()

# Load .env from project root (pi/ directory)
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)


def _bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


def _int(key: str, default: int = 0) -> int:
    return int(os.getenv(key, str(default)))


def _str(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# ── API Keys ──────────────────────────────────────────────────────────
GEMINI_API_KEY = _str("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = _str("TELEGRAM_BOT_TOKEN")
TELEGRAM_ALLOWED_USERS = _str("TELEGRAM_ALLOWED_USERS")  # comma-separated IDs

# ── Triggers ──────────────────────────────────────────────────────────
TRIGGER_WAKEWORD = _bool("TRIGGER_WAKEWORD", True)
TRIGGER_BUTTON = _bool("TRIGGER_BUTTON", True)
TRIGGER_FACE = _bool("TRIGGER_FACE", True)
TRIGGER_CLAP = _bool("TRIGGER_CLAP", False)
TRIGGER_PIR = _bool("TRIGGER_PIR", False)
TRIGGER_TELEGRAM = _bool("TRIGGER_TELEGRAM", False)

# ── AI ────────────────────────────────────────────────────────────────
AI_GEMINI_LIVE = _bool("AI_GEMINI_LIVE", True)
AI_GEMINI_FLASH = _bool("AI_GEMINI_FLASH", True)
# Ollama is used in LOCAL_SERVER / OFFLINE modes; needs server or local install
AI_OLLAMA_FALLBACK = _bool("AI_OLLAMA_FALLBACK", True)
# Live model — override with GEMINI_LIVE_MODEL in .env if the name changes
GEMINI_LIVE_MODEL = _str("GEMINI_LIVE_MODEL", "gemini-2.0-flash-live-001")

# ── Network monitoring ────────────────────────────────────────────────
# Ping host used to verify internet; change to router IP for LAN-only check
NETWORK_PING_HOST = _str("NETWORK_PING_HOST", "8.8.8.8")
# How often to re-check connectivity (seconds)
NETWORK_CHECK_INTERVAL = _int("NETWORK_CHECK_INTERVAL", 30)
# Consecutive failures before dropping from FULL_CLOUD (hysteresis)
NETWORK_FAIL_THRESHOLD = _int("NETWORK_FAIL_THRESHOLD", 2)

# ── Offline STT (Vosk — used in LOCAL_SERVER / OFFLINE modes) ────────
OFFLINE_STT_ENABLED = _bool("OFFLINE_STT_ENABLED", True)
OFFLINE_STT_MODEL = _str(
    "OFFLINE_STT_MODEL",
    str(_HOME / "vosk_models/vosk-model-small-en-us-0.15"),
)
# Max seconds to record per utterance before sending to STT
OFFLINE_MAX_UTTERANCE_S = _int("OFFLINE_MAX_UTTERANCE_S", 10)
# Max conversation turns per local session before returning to IDLE
OFFLINE_MAX_TURNS = _int("OFFLINE_MAX_TURNS", 5)

# ── Recognition backends ──────────────────────────────────────────────
FACE_DETECTOR_BACKEND = _str("FACE_DETECTOR_BACKEND", "auto")  # mediapipe|haar|auto
VAD_BACKEND           = _str("VAD_BACKEND",           "auto")  # silero|energy|auto

# ── Vision (offloaded to server) ─────────────────────────────────────
VISION_FACE_RECOGNITION = _bool("VISION_FACE_RECOGNITION", False)  # needs home server
VISION_YOLO = _bool("VISION_YOLO", False)
VISION_GESTURE = _bool("VISION_GESTURE", False)
VISION_ANOMALY = _bool("VISION_ANOMALY", False)

# ── MCP Tools ─────────────────────────────────────────────────────────
TOOL_MUSIC = _bool("TOOL_MUSIC", False)
TOOL_WEB_SEARCH = _bool("TOOL_WEB_SEARCH", True)
TOOL_HOME_ASSISTANT = _bool("TOOL_HOME_ASSISTANT", False)
TOOL_MOTOR = _bool("TOOL_MOTOR", False)
TOOL_GPIO = _bool("TOOL_GPIO", False)
TOOL_CAMERA_PTZ = _bool("TOOL_CAMERA_PTZ", True)
TOOL_MEMORY = _bool("TOOL_MEMORY", True)

# ── Hardware ──────────────────────────────────────────────────────────
HW_MOTORS = _bool("HW_MOTORS", False)
HW_SERVOS = _bool("HW_SERVOS", False)
HW_SENSORS = _bool("HW_SENSORS", False)

# ── Server (Pi + Server mode) ─────────────────────────────────────────
# Set SERVER_ENABLED=true when a home server is running jarvis-server.
SERVER_ENABLED = _bool("SERVER_ENABLED", False)
SERVER_HOST = _str("SERVER_HOST", "jarvis-server.local")
SERVER_PORT = _int("SERVER_PORT", 9000)
SERVER_HEALTH_INTERVAL = _int("SERVER_HEALTH_INTERVAL", 30)  # seconds

# ── Audio ─────────────────────────────────────────────────────────────
AUDIO_DEVICE_INDEX = _int("AUDIO_DEVICE_INDEX", -1)  # -1 = auto
AUDIO_SAMPLE_RATE = _int("AUDIO_SAMPLE_RATE", 48000)
AUDIO_TARGET_RATE = _int("AUDIO_TARGET_RATE", 16000)
AUDIO_CHUNK_SIZE = _int("AUDIO_CHUNK_SIZE", 1024)

# ── Wake Word ─────────────────────────────────────────────────────────
def _wakeword_model_default() -> str:
    """Return configured path, or auto-locate from ~/wakeword_models/ or openwakeword package."""
    import glob as _glob
    configured = os.getenv("WAKEWORD_MODEL_PATH", "")

    # 1. Explicit env var — use if it exists
    if configured and Path(configured).exists():
        return configured

    # 2. Scan ~/wakeword_models/ for any jarvis model (covers hey_jarvis_v0.1.onnx, etc.)
    user_models_dir = _HOME / "wakeword_models"
    for pattern in ("*hey_jarvis*.onnx", "*jarvis*.onnx"):
        matches = sorted(_glob.glob(str(user_models_dir / pattern)))
        if matches:
            return matches[0]

    # 3. Fall back to bundled model inside the installed openwakeword package
    try:
        import openwakeword as _oww
        pkg_models = Path(_oww.__file__).parent / "resources" / "models"
        for pattern in ("*hey_jarvis*", "*jarvis*"):
            matches = _glob.glob(str(pkg_models / pattern))
            if matches:
                return matches[0]
    except Exception:
        pass

    # 4. Return default path even if missing — wakeword_trigger handles the error
    return str(user_models_dir / "hey_jarvis.onnx")

WAKEWORD_MODEL_PATH = _wakeword_model_default()
WAKEWORD_THRESHOLD = float(os.getenv("WAKEWORD_THRESHOLD", "0.4"))

# ── TTS ───────────────────────────────────────────────────────────────
PIPER_MODEL_PATH = _str("PIPER_MODEL_PATH", str(_HOME / "piper_models/en_US-lessac-medium.onnx"))
PIPER_CONFIG_PATH = _str("PIPER_CONFIG_PATH", str(_HOME / "piper_models/en_US-lessac-medium.onnx.json"))

# ── Camera ────────────────────────────────────────────────────────────
CAMERA_DEVICE = _str("CAMERA_DEVICE", "/dev/video0")
CAMERA_FRAME_WIDTH = _int("CAMERA_FRAME_WIDTH", 640)
CAMERA_FRAME_HEIGHT = _int("CAMERA_FRAME_HEIGHT", 480)
CAMERA_CAPTURE_INTERVAL = _int("CAMERA_CAPTURE_INTERVAL", 5)  # seconds

# ── GPIO Pins ─────────────────────────────────────────────────────────
GPIO_BUTTON_PIN = _int("GPIO_BUTTON_PIN", 17)
GPIO_PIR_PIN = _int("GPIO_PIR_PIN", 27)
GPIO_RELAY_PINS = _str("GPIO_RELAY_PINS", "22,23,24,25")  # comma-separated
GPIO_EMERGENCY_STOP_PIN = _int("GPIO_EMERGENCY_STOP_PIN", 5)

# ── Motors ────────────────────────────────────────────────────────────
MOTOR_ENA_PIN = _int("MOTOR_ENA_PIN", 12)
MOTOR_IN1_PIN = _int("MOTOR_IN1_PIN", 6)
MOTOR_IN2_PIN = _int("MOTOR_IN2_PIN", 13)
MOTOR_ENB_PIN = _int("MOTOR_ENB_PIN", 18)
MOTOR_IN3_PIN = _int("MOTOR_IN3_PIN", 19)
MOTOR_IN4_PIN = _int("MOTOR_IN4_PIN", 26)
MOTOR_MAX_SPEED = _int("MOTOR_MAX_SPEED", 80)  # PWM duty cycle 0-100

# ── Trigger Manager ──────────────────────────────────────────────────
TRIGGER_COOLDOWN = float(os.getenv("TRIGGER_COOLDOWN", "3.0"))  # seconds

# ── MQTT / Home Assistant ────────────────────────────────────────────
MQTT_BROKER = _str("MQTT_BROKER", "")
MQTT_PORT = _int("MQTT_PORT", 1883)
MQTT_USERNAME = _str("MQTT_USERNAME", "")
MQTT_PASSWORD = _str("MQTT_PASSWORD", "")

# ── Memory ────────────────────────────────────────────────────────────
MEMORY_DB_PATH = _str("MEMORY_DB_PATH", str(_HOME / "jarvis/data/jarvis.db"))
MEMORY_SHORT_TERM_LIMIT = _int("MEMORY_SHORT_TERM_LIMIT", 5)
MEMORY_RETENTION_DAYS = _int("MEMORY_RETENTION_DAYS", 30)

# ── Logging ───────────────────────────────────────────────────────────
LOG_LEVEL = _str("LOG_LEVEL", "INFO")

# ── Display ────────────────────────────────────────────────────────────
DISPLAY_ENABLED = _bool("DISPLAY_ENABLED", True)
DISPLAY_WIDTH = _int("DISPLAY_WIDTH", 800)
DISPLAY_HEIGHT = _int("DISPLAY_HEIGHT", 480)
DISPLAY_FPS = _int("DISPLAY_FPS", 30)
DISPLAY_FULLSCREEN = _bool("DISPLAY_FULLSCREEN", False)
DISPLAY_BRIGHTNESS = _int("DISPLAY_BRIGHTNESS", 80)  # 0-100
DISPLAY_IDLE_TIMEOUT = _int("DISPLAY_IDLE_TIMEOUT", 300)  # seconds before screen dims

# ── MCP Server ────────────────────────────────────────────────────────
MCP_HOST = _str("MCP_HOST", "127.0.0.1")
MCP_PORT = _int("MCP_PORT", 8080)
