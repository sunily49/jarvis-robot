# JARVIS Robot — Raspberry Pi 5 Deployment Guide

Complete walkthrough: fresh Pi → running autonomous robot with auto-boot.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Pi OS Setup](#2-pi-os-setup)
3. [Hardware Wiring](#3-hardware-wiring)
4. [Software Installation](#4-software-installation)
5. [Configuration](#5-configuration)
6. [Hardware Verification](#6-hardware-verification)
7. [First Run (Manual)](#7-first-run-manual)
8. [Systemd Auto-Start](#8-systemd-auto-start)
9. [Monitoring & Logs](#9-monitoring--logs)
10. [OTA Updates](#10-ota-updates)
11. [Server Setup (Optional)](#11-server-setup-optional)
12. [Troubleshooting](#12-troubleshooting)
13. [Pin Reference](#13-pin-reference)

---

## 1. Prerequisites

### Hardware Required

| Component | Model | Est. Cost (INR) |
|---|---|---|
| Raspberry Pi 5 | 8GB RAM | Rs. 6,500 |
| MicroSD Card | 64GB+ Class 10 | Rs. 600 |
| USB-C Power Supply | 5V 5A (27W) official | Rs. 1,200 |
| Camera + Mic | EMEET PIXY PTZ (USB) | Rs. 8,000 |
| USB Speaker | Any USB/3.5mm speaker | Rs. 500 |
| Push Button | Momentary switch | Rs. 20 |
| Jumper Wires | Male-to-female | Rs. 50 |

### Optional Hardware (enable via .env flags)

| Component | For | Flag | Cost |
|---|---|---|---|
| HC-SR501 PIR Sensor | Motion trigger | `TRIGGER_PIR` | Rs. 50 |
| HC-SR04 Ultrasonic | Distance sensing | `HW_SENSORS` | Rs. 80 |
| DHT22 Temp/Humidity | Environment | `HW_SENSORS` | Rs. 200 |
| L298N Motor Driver | DC motors | `HW_MOTORS` | Rs. 150 |
| PCA9685 Servo Board | Servos | `HW_SERVOS` | Rs. 400 |
| Relay Module (4-ch) | Light/appliance control | `TOOL_GPIO` | Rs. 150 |

### Accounts Required

- **Google AI Studio** — get a Gemini API key at https://aistudio.google.com/apikey
- **Telegram** (optional) — create a bot via @BotFather for remote control

---

## 2. Pi OS Setup

### 2.1 Flash Raspberry Pi OS

1. Download **Raspberry Pi Imager** on your PC
2. Choose OS: **Raspberry Pi OS (64-bit) Bookworm**
3. Click the gear icon (Advanced):
   - Set hostname: `jarvis`
   - Enable SSH: yes
   - Set username: `admin` (password: your choice)
   - Configure WiFi (if not using ethernet)
   - Set locale/timezone
4. Flash to SD card, insert into Pi, boot

### 2.2 First Boot (SSH)

```bash
ssh admin@jarvis.local
```

### 2.3 System Update

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

### 2.4 Enable Interfaces

```bash
sudo raspi-config
```

Navigate to **Interface Options** and enable:
- **I2C** (for PCA9685 servo board)
- **SPI** (for future sensors)
- **Camera** (legacy camera support — also works with USB)

```bash
sudo reboot
```

### 2.5 Add User to Required Groups

```bash
sudo usermod -aG gpio,video,audio,i2c,spi,dialout admin
```

Log out and back in for groups to take effect.

---

## 3. Hardware Wiring

### 3.1 Basic Setup (Minimum)

```
EMEET PIXY Camera ──── USB port (any)
USB Speaker ─────────── USB port or 3.5mm jack
Push Button ─────────── GPIO 17 + GND
```

**Push Button Wiring:**
```
GPIO 17 (Pin 11) ──── Button ──── GND (Pin 9)
```
The code uses internal pull-up resistor, so no external resistor needed.

### 3.2 PIR Motion Sensor (optional)

```
PIR VCC ──── 5V (Pin 2)
PIR OUT ──── GPIO 27 (Pin 13)
PIR GND ──── GND (Pin 6)
```

### 3.3 Relay Module (optional)

```
Relay VCC ──── 5V (Pin 4)
Relay GND ──── GND (Pin 14)
Relay IN1 ──── GPIO 22 (Pin 15)
Relay IN2 ──── GPIO 23 (Pin 16)
Relay IN3 ──── GPIO 24 (Pin 18)
Relay IN4 ──── GPIO 25 (Pin 22)
```

### 3.4 Ultrasonic HC-SR04 (optional)

```
HC-SR04 VCC ──── 5V
HC-SR04 TRIG ─── GPIO 23 (Pin 16)
HC-SR04 ECHO ─── 1kΩ resistor ─── GPIO 24 (Pin 18) ─── 2kΩ resistor ─── GND
HC-SR04 GND ──── GND
```
**Note:** Voltage divider on ECHO is required (5V → 3.3V).

### 3.5 Motor Driver L298N (optional)

```
L298N ENA ──── GPIO 12 (Pin 32) [PWM]
L298N IN1 ──── GPIO 6  (Pin 31)
L298N IN2 ──── GPIO 13 (Pin 33)
L298N ENB ──── GPIO 18 (Pin 12) [PWM]
L298N IN3 ──── GPIO 19 (Pin 35)
L298N IN4 ──── GPIO 26 (Pin 37)
L298N GND ──── GND (Pin 39) + Motor battery GND
L298N 12V ──── Motor battery +V (6-12V)
L298N 5V  ──── Not connected (Pi has own power)
```

### 3.6 Emergency Stop Button

```
GPIO 5 (Pin 29) ──── NC Button ──── GND (Pin 30)
```
Normally-closed button: pressed = circuit breaks = emergency stop.

### GPIO Pin Map Summary

| GPIO | Pin | Function | Flag |
|---|---|---|---|
| 5 | 29 | Emergency Stop | `HW_MOTORS` |
| 6 | 31 | Motor IN1 | `HW_MOTORS` |
| 12 | 32 | Motor ENA (PWM) | `HW_MOTORS` |
| 13 | 33 | Motor IN2 | `HW_MOTORS` |
| 17 | 11 | **Push Button** | `TRIGGER_BUTTON` |
| 18 | 12 | Motor ENB (PWM) | `HW_MOTORS` |
| 19 | 35 | Motor IN3 | `HW_MOTORS` |
| 22 | 15 | Relay CH1 | `TOOL_GPIO` |
| 23 | 16 | Relay CH2 / Ultrasonic TRIG | `TOOL_GPIO` / `HW_SENSORS` |
| 24 | 18 | Relay CH3 / Ultrasonic ECHO | `TOOL_GPIO` / `HW_SENSORS` |
| 25 | 22 | Relay CH4 | `TOOL_GPIO` |
| 26 | 37 | Motor IN4 | `HW_MOTORS` |
| 27 | 13 | PIR Sensor | `TRIGGER_PIR` |

---

## 4. Software Installation

### 4.1 One-Command Install

```bash
cd ~
git clone <your-repo-url> jarvis
cd jarvis
make install
```

Or manually:

```bash
bash scripts/install_pi.sh
```

The install script will:
1. Check Pi model, RAM, OS, and internet
2. Install system packages (portaudio, opencv, v4l-utils, mpv, etc.)
3. Create Python virtual environment + install dependencies
4. Install RPi.GPIO and Adafruit libraries
5. Create data directories
6. Download wake word ONNX model
7. Download Piper TTS voice model
8. Create `.env` from template
9. Install and enable systemd service
10. Configure ALSA for USB audio

**Re-running is safe** — the script is idempotent.

### 4.2 Skip Model Download (for re-installs)

```bash
bash scripts/install_pi.sh --skip-models
```

---

## 5. Configuration

### 5.1 Edit Environment File

```bash
nano ~/jarvis/pi/.env
```

**Minimum required changes:**

```ini
# Your Gemini API key (REQUIRED)
GEMINI_API_KEY=AIzaSy...your_key_here

# Telegram bot token (optional, for remote control)
TELEGRAM_BOT_TOKEN=123456:ABC...your_token
TELEGRAM_ALLOWED_USERS=your_telegram_user_id
```

### 5.2 Find Your Audio Device

```bash
# List all audio devices
~/jarvis/venv/bin/python3 -c "
import pyaudio
p = pyaudio.PyAudio()
for i in range(p.get_device_count()):
    d = p.get_device_info_by_index(i)
    direction = 'IN' if d['maxInputChannels'] > 0 else 'OUT'
    print(f\"  [{i}] {direction}: {d['name']}\")
p.terminate()
"
```

Set the input device index in `.env`:
```ini
AUDIO_DEVICE_INDEX=2  # Replace with your mic device index (-1 for auto)
```

### 5.3 Find Your Camera

```bash
v4l2-ctl --list-devices
ls -la /dev/video*
```

Set in `.env` if not `/dev/video0`:
```ini
CAMERA_DEVICE=/dev/video0
```

### 5.4 Configure Feature Flags

Enable only what you have wired:

```ini
# Start with these — add more later
TRIGGER_WAKEWORD=true
TRIGGER_BUTTON=true
TRIGGER_FACE=true
TRIGGER_CLAP=false
TRIGGER_PIR=false        # Set true if PIR wired to GPIO 27
TRIGGER_TELEGRAM=false   # Set true if bot token configured

TOOL_MOTOR=false         # Set true if L298N wired
TOOL_GPIO=false          # Set true if relays wired
HW_MOTORS=false
HW_SERVOS=false
HW_SENSORS=false         # Set true if ultrasonic/DHT22 wired

SERVER_ENABLED=false     # Set true when server is set up
```

---

## 6. Hardware Verification

Run the hardware diagnostic:

```bash
make hw-test
# or
~/jarvis/venv/bin/python3 scripts/test_hardware.py
```

Expected output:
```
==================================================
  JARVIS Hardware Diagnostic
==================================================

[Camera]
  ✓ Camera OK — frame: (480, 640, 3)

[Microphone]
  ✓ Default input: EMEET PIXY (index=2)

[Speaker]
  ✓ Speaker devices found

[GPIO]
  ✓ GPIO OK — Pi 5, Rev ...

[I2C]
  ○ I2C bus OK but no devices detected

[Network]
  ✓ Internet OK
  ✓ Hostname: jarvis, IP: 192.168.1.xx

[PTZ Camera (v4l2)]
  ✓ v4l2 devices found

==================================================
  Results: 7/7 passed
==================================================
```

### Quick Manual Tests

```bash
# Test microphone (record 3 seconds)
arecord -d 3 -f S16_LE -r 16000 /tmp/test.wav

# Play it back
aplay /tmp/test.wav

# Test camera (capture a frame)
v4l2-ctl -d /dev/video0 --stream-mmap --stream-count=1 --stream-to=/tmp/test.raw

# Test GPIO (quick Python check)
python3 -c "import RPi.GPIO as GPIO; print(GPIO.RPI_INFO)"
```

---

## 7. First Run (Manual)

Start JARVIS manually to see output directly:

```bash
cd ~/jarvis/pi
source ~/jarvis/venv/bin/activate
python -m jarvis.main
```

You should see:
```
2026-04-11 10:00:00 [INFO] jarvis: ============================================================
2026-04-11 10:00:00 [INFO] jarvis: JARVIS Robot starting up...
2026-04-11 10:00:00 [INFO] jarvis: ============================================================
2026-04-11 10:00:00 [INFO] jarvis: Loading enabled modules...
2026-04-11 10:00:01 [INFO] trigger_manager: Registered trigger: wakeword (priority=NORMAL)
2026-04-11 10:00:01 [INFO] trigger_manager: Registered trigger: button (priority=CRITICAL)
2026-04-11 10:00:01 [INFO] trigger_manager: Registered trigger: face (priority=NORMAL)
2026-04-11 10:00:01 [INFO] jarvis: Loaded triggers: ['wakeword', 'button', 'face']
2026-04-11 10:00:01 [INFO] jarvis: Loaded tools: 8
2026-04-11 10:00:02 [INFO] audio_capture: Audio capture started: 48000Hz → 16000Hz
2026-04-11 10:00:02 [INFO] server_client: Server integration disabled
2026-04-11 10:00:02 [INFO] conversation_memory: Conversation memory initialized
2026-04-11 10:00:02 [INFO] tts: Announcement: JARVIS online. All systems operational.
2026-04-11 10:00:03 [INFO] jarvis: Startup complete. Listening for triggers...
```

**Test it:**
- Say "Hey Jarvis" → should trigger wake word → Gemini Live session starts
- Press the push button → immediate trigger
- Stand in front of camera → face detection trigger

Press `Ctrl+C` to stop.

---

## 8. Systemd Auto-Start

### 8.1 Enable and Start

```bash
# Already enabled by install script, but to start now:
sudo systemctl start jarvis

# Verify it's running
sudo systemctl status jarvis
```

### 8.2 Service Commands

```bash
make start          # Start JARVIS
make stop           # Stop JARVIS
make restart        # Restart JARVIS
make status         # Show service status
make logs           # Follow live logs
```

Or directly:

```bash
sudo systemctl start jarvis
sudo systemctl stop jarvis
sudo systemctl restart jarvis
sudo systemctl status jarvis
journalctl -u jarvis -f              # Live log stream
journalctl -u jarvis --since today   # Today's logs
journalctl -u jarvis -n 100          # Last 100 lines
```

### 8.3 Boot Behavior

After `systemctl enable jarvis`:
- JARVIS starts automatically 30s after boot (after network is ready)
- If JARVIS crashes, systemd restarts it after 5 seconds
- Resource limits: max 2GB RAM, max 85% CPU

### 8.4 Verify Auto-Start

```bash
sudo reboot
# Wait 60 seconds, then SSH back in
ssh admin@jarvis.local
sudo systemctl status jarvis   # Should show "active (running)"
journalctl -u jarvis -n 20     # Should show startup logs
```

---

## 9. Monitoring & Logs

### 9.1 Health Check

```bash
make health
# or
bash scripts/health_check.sh
```

Output:
```
JARVIS Health Check — 2026-04-11 10:30:00
──────────────────────────────────────────
Service:     ✓ running (pid 1234, uptime 2h 15m)
CPU:         ✓ 42% (limit: 85%)
Memory:      ✓ 1.2G / 8.0G (15%)
Temperature: ✓ 52°C (throttle at 80°C)
Camera:      ✓ /dev/video0 available
Network:     ✓ internet OK
Gemini API:  ✓ reachable
Server:      ○ disabled
──────────────────────────────────────────
Status: HEALTHY (7/7)
```

### 9.2 Automated Health Monitoring (cron)

```bash
# Run health check every 5 minutes, log to file
crontab -e
# Add this line:
*/5 * * * * /home/admin/jarvis/scripts/health_check.sh --quiet >> /home/admin/jarvis/pi/data/health.log 2>&1
```

### 9.3 Log Rotation

Install the logrotate config:
```bash
sudo cp ~/jarvis/pi/deploy/jarvis-logrotate.conf /etc/logrotate.d/jarvis
```

This keeps 7 days of logs, compresses old ones, and caps journal size at 100MB.

---

## 10. OTA Updates

### 10.1 Update from Git

```bash
make update
# or
bash scripts/update_pi.sh
```

This will:
1. Save current commit hash (for rollback)
2. `git pull` latest code
3. `pip install -r requirements.txt` (if deps changed)
4. `systemctl restart jarvis`
5. Verify JARVIS starts within 30 seconds
6. Auto-rollback if startup fails

### 10.2 Manual Update

```bash
cd ~/jarvis
git pull
source venv/bin/activate
pip install -r pi/requirements.txt
sudo systemctl restart jarvis
journalctl -u jarvis -f  # Watch for errors
```

### 10.3 Rollback

```bash
cd ~/jarvis
git log --oneline -5        # Find the good commit
git checkout <commit-hash>  # Go back
sudo systemctl restart jarvis
```

---

## 11. Server Setup (Optional)

If you have a home PC/server for ML offloading:

```bash
# On the server machine:
git clone <repo> ~/jarvis-server-repo
cd ~/jarvis-server-repo
bash scripts/install_server.sh
sudo systemctl start jarvis-server
```

Then on the Pi, update `.env`:
```ini
SERVER_ENABLED=true
SERVER_HOST=192.168.1.100   # Your server's IP
SERVER_PORT=9000
```

```bash
sudo systemctl restart jarvis
```

The Pi will auto-detect the server via health checks and offload face recognition, YOLO, and Ollama LLM.

---

## 12. Troubleshooting

### JARVIS won't start

```bash
# Check logs for the error
journalctl -u jarvis -n 50 --no-pager

# Common fixes:
# 1. Missing API key
grep GEMINI_API_KEY ~/jarvis/pi/.env

# 2. Audio device not found
arecord -l  # List input devices
aplay -l    # List output devices

# 3. Camera not found
v4l2-ctl --list-devices
ls -la /dev/video*

# 4. Permission denied on GPIO
groups  # Should include: gpio video audio i2c
```

### No audio input

```bash
# Check ALSA config
cat /proc/asound/cards

# Test recording
arecord -D plughw:2,0 -d 3 -f S16_LE -r 16000 /tmp/test.wav
aplay /tmp/test.wav

# If wrong device, update .env:
AUDIO_DEVICE_INDEX=2  # Match your card number
```

### Camera not detected

```bash
# Check USB devices
lsusb | grep -i camera

# Check video devices
v4l2-ctl --list-devices

# Test capture
v4l2-ctl -d /dev/video0 --all

# If /dev/video0 is not the EMEET, try /dev/video2
CAMERA_DEVICE=/dev/video2
```

### Wake word not triggering

```bash
# Check model file exists
ls -la ~/wakeword_models/

# Test in isolation
cd ~/jarvis/pi
source ~/jarvis/venv/bin/activate
python -c "
from openwakeword.model import Model
m = Model(wakeword_models=['/home/admin/wakeword_models/hey_jarvis.onnx'])
print('Model loaded OK, classes:', list(m.prediction_buffer.keys()))
"

# Lower threshold if needed
# In .env: WAKEWORD_THRESHOLD=0.5
```

### Gemini API errors

```bash
# Test API key
curl -s "https://generativelanguage.googleapis.com/v1beta/models?key=YOUR_KEY" | head -5

# Common issues:
# - Invalid key → regenerate at aistudio.google.com
# - Quota exceeded → wait or upgrade plan
# - Network issue → check internet: ping 8.8.8.8
```

### High CPU / overheating

```bash
# Check temperature
vcgencmd measure_temp

# Check per-process CPU
top -p $(pgrep -f jarvis.main)

# Reduce load — disable heavy features in .env:
TRIGGER_FACE=false     # Saves ~8% CPU
VISION_YOLO=false      # Saves ~15% CPU (if running locally)
```

### Systemd service keeps restarting

```bash
# Check why it's failing
journalctl -u jarvis --since "5 minutes ago"

# Check for import errors
cd ~/jarvis/pi
source ~/jarvis/venv/bin/activate
python -c "from jarvis.config import settings; print('Config OK')"
python -c "from jarvis.main import main; print('Imports OK')"
```

---

## 13. Pin Reference

### Raspberry Pi 5 GPIO Header (40 pins)

```
                    3V3  (1)  (2)  5V
          I2C SDA   GP2  (3)  (4)  5V
          I2C SCL   GP3  (5)  (6)  GND
                    GP4  (7)  (8)  GP14  UART TX
                    GND  (9)  (10) GP15  UART RX
  BUTTON ★  GP17  (11) (12) GP18  MOTOR ENB ★
     PIR ★  GP27  (13) (14) GND
  RELAY1 ★  GP22  (15) (16) GP23  RELAY2 / ULTRASONIC TRIG ★
                   3V3  (17) (18) GP24  RELAY3 / ULTRASONIC ECHO ★
         SPI MOSI GP10  (19) (20) GND
         SPI MISO GP9   (21) (22) GP25  RELAY4 ★
         SPI SCLK GP11  (23) (24) GP8
                    GND  (25) (26) GP7
                    GP0  (27) (28) GP1
   E-STOP ★  GP5  (29) (30) GND
  MOTOR IN1 ★ GP6  (31) (32) GP12  MOTOR ENA ★
  MOTOR IN2 ★ GP13  (33) (34) GND
  MOTOR IN3 ★ GP19  (35) (36) GP16
  MOTOR IN4 ★ GP26  (37) (38) GP20
                    GND  (39) (40) GP21
```

★ = Used by JARVIS (configurable in .env)

---

## Quick Reference Card

```bash
make install     # Full installation
make start       # Start JARVIS
make stop        # Stop JARVIS
make restart     # Restart JARVIS
make logs        # Follow live logs
make status      # Service status
make health      # Full health check
make hw-test     # Hardware diagnostics
make update      # Pull latest + restart
make test        # Run pytest suite
```
