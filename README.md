# JARVIS — Enterprise-Grade Autonomous Robot

> AI-powered robot on Raspberry Pi 5 with Gemini Live voice AI, hybrid compute offloading, face/voice recognition, and a modular plugin architecture.

```
git clone https://github.com/sunily49/jarvis-robot.git
cd jarvis-robot
make install
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Raspberry Pi 5  (always-on, safety-critical)               │
│                                                             │
│  Triggers ──► TriggerManager ──► SessionManager             │
│    ├── Wake Word  (openWakeWord ONNX)                       │
│    ├── Push Button (GPIO, CRITICAL priority)  ┌───────────┐ │
│    ├── Face Presence (Haar cascade, ~8% CPU)  │Gemini Live│ │
│    ├── Double Clap (FFT energy detection)     │voice↔voice│ │
│    ├── PIR Motion (HC-SR501)                  └───────────┘ │
│    └── Telegram Bot (/wake /photo /status /register)        │
│                                                             │
│  Audio:   Mic → 16kHz PCM → Gemini Live WS → Speaker       │
│  Fallback TTS: Piper (system announcements / offline)       │
│                                                             │
│  MCP Tools (FastAPI :8080, Gemini function-calling):        │
│    Camera PTZ | Motors | GPIO/Relays | Sensors              │
│    Music | Web Search | Memory | Display | Person           │
│                                                             │
│  Drivers:  GPIO | L298N Motors | PCA9685 Servos | SensorBus │
│  Memory:   SQLite (exchanges · entities · summaries)        │
│  Display:  Pygame HDMI — animated face + status dashboard   │
└──────────────────────┬──────────────────────────────────────┘
                       │  WebSocket (vision frames)
                       │  REST (face · voice · YOLO · LLM)
┌──────────────────────▼──────────────────────────────────────┐
│  Home Server  (optional — graceful degradation when off)    │
│                                                             │
│  Face Recognition (dlib 128-d encodings)                    │
│  Voice ID        (resemblyzer d-vector embeddings)          │
│  Person Registry (faces + voices + preferences, JSON)       │
│  YOLOv8 Object Detection                                    │
│  MediaPipe Gesture Recognition                              │
│  Ollama LLM (mistral-7b) — fallback when Gemini offline     │
│  Anomaly Detection (adaptive z-score baselines)             │
└─────────────────────────────────────────────────────────────┘
```

---

## Feature Flags

Every module is a boolean in `pi/.env` — flip to `true`/`false`:

| Flag | Default | What it enables |
|---|---|---|
| `TRIGGER_WAKEWORD` | `true` | "Hey Jarvis" openWakeWord detection |
| `TRIGGER_BUTTON` | `true` | GPIO push button (CRITICAL priority) |
| `TRIGGER_FACE` | `true` | Face presence + server-side ID |
| `TRIGGER_CLAP` | `false` | Double-clap audio pattern |
| `TRIGGER_PIR` | `false` | HC-SR501 PIR motion sensor |
| `TRIGGER_TELEGRAM` | `false` | Telegram bot remote control |
| `TOOL_CAMERA_PTZ` | `true` | Camera pan/tilt/zoom + scene description |
| `TOOL_MOTOR` | `false` | Drive forward/backward/turn |
| `TOOL_GPIO` | `false` | Relay/light control |
| `TOOL_WEB_SEARCH` | `true` | DuckDuckGo + Wikipedia |
| `TOOL_MUSIC` | `false` | YouTube Music via mpv |
| `TOOL_MEMORY` | `true` | Recall conversations + save notes |
| `HW_MOTORS` | `false` | L298N motor driver |
| `HW_SERVOS` | `false` | PCA9685 servo board |
| `HW_SENSORS` | `false` | HC-SR04 ultrasonic + DHT22 |
| `SERVER_ENABLED` | `false` | Home server ML offloading |
| `DISPLAY_ENABLED` | `false` | HDMI animated face display |
| `VISION_FACE_RECOGNITION` | `false` | Face register/identify tools |
| `AI_OLLAMA_FALLBACK` | `true` | Fallback to Ollama when Gemini offline |

---

## Quick Start

### Pi Setup
```bash
git clone https://github.com/sunily49/jarvis-robot.git ~/jarvis
cd ~/jarvis
make install            # installs everything, sets up systemd
nano pi/.env            # set GEMINI_API_KEY at minimum
make hw-test            # verify camera, mic, GPIO
make start              # start via systemd
make logs               # watch live output
```

### Server Setup (optional, for ML offloading)
```bash
bash scripts/install_server.sh
sudo systemctl start jarvis-server
# Then on Pi: set SERVER_ENABLED=true, SERVER_HOST=<server-ip>
```

---

## Make Commands

```bash
make install     # full Pi setup (idempotent)
make start       # systemd start
make stop        # systemd stop
make restart     # systemd restart
make logs        # live log stream
make status      # service + resource usage
make health      # full health check (CPU, temp, camera, API)
make hw-test     # hardware diagnostics
make update      # git pull → pip install → restart → auto-rollback
make test        # pytest suite
make config      # edit .env
make config-show # print all active settings
```

---

## Extending JARVIS

### Add a Trigger
```python
# pi/jarvis/triggers/my_trigger.py
from jarvis.core.trigger_manager import BaseTrigger, TriggerPriority, TriggerManager
from jarvis.config import settings

class MyTrigger(BaseTrigger):
    name = "my_trigger"
    priority = TriggerPriority.NORMAL

    async def start(self) -> None:
        while True:
            # detect something...
            await self.fire(confidence=0.9, data={"source": "my_trigger"})

if settings.TRIGGER_MY:
    TriggerManager.register(MyTrigger())
```
Then add `TRIGGER_MY=false` to `.env.example` and one import line in `main.py`.

### Add a Sensor
```python
from jarvis.drivers.sensor_bus import sensor_bus

sensor_bus.register("light", read_fn=read_lux, interval=2.0, unit="lux")
sensor_bus.set_threshold("light", max_val=1000, event="sensor.light_alert")
```

### Add a Gemini Tool
```python
from jarvis.tools.mcp_server import mcp_tool

@mcp_tool(name="greet", description="Say hello", parameters={
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
})
async def greet(name: str) -> dict:
    return {"message": f"Hello, {name}!"}
```

---

## Face & Voice Learning

| Action | How |
|---|---|
| Register face | Say "Remember this person, their name is Sarah" or Telegram `/register Sarah` |
| Register voice | Say "Learn my voice, I'm Sarah" — records 5s of speech |
| Auto-greet | Robot greets known people by name on face detection |
| Person profile | Preferences, notes, encounter count stored on server |

---

## Display Modes (F1–F5)

| Key | Screen |
|---|---|
| F1 | Animated robot face (9 emotions: neutral, happy, sad, angry, surprised, thinking, listening, speaking, sleeping) |
| F2 | System status (CPU, memory, temperature, server, uptime) |
| F3 | Conversation transcript |
| F4 | Live camera feed |
| F5 | Split — face + status |

---

## Hardware

| Component | Purpose | GPIO / Interface |
|---|---|---|
| EMEET PIXY USB Camera | Vision + PTZ | USB / v4l2 |
| USB Microphone | Wake word + Gemini Live | USB / ALSA |
| USB Speaker | Audio output | USB / ALSA |
| Push Button | CRITICAL trigger | GPIO 17 |
| HC-SR501 PIR | Motion trigger | GPIO 27 |
| HC-SR04 Ultrasonic | Distance / obstacle | GPIO 23/24 |
| DHT22 | Temperature + humidity | GPIO sensor bus |
| L298N | DC motor drive | GPIO 6/12/13/18/19/26 |
| PCA9685 | 16-ch servo control | I2C |
| 4-ch Relay | Lights / appliances | GPIO 22/23/24/25 |
| HDMI Mini Display | Robot face UI | HDMI |

---

## Tests
```bash
pytest tests/ -v
python3 scripts/test_hardware.py  # hardware diagnostics
bash scripts/health_check.sh      # full system health
```

---

## License
MIT
