# JARVIS — Enterprise-Grade Autonomous Robot

AI-powered robot running on Raspberry Pi 5 with hybrid compute offloading to a home server.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Raspberry Pi 5 (always-on, safety-critical)        │
│                                                     │
│  Triggers → TriggerManager → SessionManager         │
│    ├── Wake Word (openWakeWord ONNX)                │
│    ├── Push Button (GPIO)          ┌──────────────┐ │
│    ├── Face Presence (Haar)        │ Gemini Live   │ │
│    ├── Clap Detection              │ (voice↔voice) │ │
│    ├── PIR Motion                  └──────────────┘ │
│    └── Telegram Bot                                 │
│                                                     │
│  Drivers: GPIO | Motors | Servos | Sensors          │
│  MCP Tools: Camera | Music | Web | Home | Memory    │
│  Audio: Capture → Gemini Live → Speaker             │
│  Fallback TTS: Piper (announcements/offline)        │
└──────────────────────┬──────────────────────────────┘
                       │ WebSocket + REST
┌──────────────────────▼──────────────────────────────┐
│  Home Server (optional, graceful degradation)        │
│                                                      │
│  Face Recognition | YOLOv8 | MediaPipe Gestures      │
│  Ollama LLM (mistral-7b) | Anomaly Detection         │
└──────────────────────────────────────────────────────┘
```

## Quick Start

### Pi Setup
```bash
git clone <repo> ~/jarvis
cd ~/jarvis
bash scripts/install_pi.sh
nano pi/.env  # Set GEMINI_API_KEY
sudo systemctl start jarvis
journalctl -u jarvis -f
```

### Server Setup (optional)
```bash
bash scripts/install_server.sh
sudo systemctl start jarvis-server
```

## Feature Flags

Every module is gated by a boolean in `.env`. Enable/disable by changing `true`/`false`:

```ini
TRIGGER_WAKEWORD=true    # Wake word detection
TRIGGER_BUTTON=true      # GPIO push button
TRIGGER_FACE=true        # Face presence trigger
TOOL_MUSIC=false         # YouTube Music playback
HW_MOTORS=false          # DC motor control
SERVER_ENABLED=true      # Home server offloading
```

## Adding a New Trigger

1. Create `pi/jarvis/triggers/my_trigger.py` implementing `BaseTrigger`
2. Add `TRIGGER_MY=false` to `.env.example`
3. Add loader line in `main.py`

## Adding a New Sensor

```python
from jarvis.drivers.sensor_bus import sensor_bus
sensor_bus.register("my_sensor", read_fn=my_read_fn, interval=2.0, unit="lux")
sensor_bus.set_threshold("my_sensor", max_val=1000, event="sensor.light_alert")
```

## Adding a New MCP Tool

```python
from jarvis.tools.mcp_server import mcp_tool

@mcp_tool(name="my_tool", description="Does something", parameters={...})
async def my_tool(arg: str) -> dict:
    return {"result": "done"}
```

## Tests

```bash
cd ~/jarvis
pytest tests/ -v
python3 scripts/test_hardware.py  # Hardware diagnostics
```
