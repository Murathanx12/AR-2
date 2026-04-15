# Sonny -- Project Alfred Robotic Butler

Sonny is a mecanum-wheeled robotic butler built for the HKU School of Innovation INTC1002 coursework (Project Alfred / Minilab 6). It follows floor tracks, navigates to ArUco markers, detects obstacles, recognises voice commands and hand gestures, and holds conversations powered by Claude AI.

**Demo date:** April 24, 2026  
**Repository:** https://github.com/Murathanx12/AR-2

---

## Architecture

Sonny uses a split-brain design:

| Component | Role |
|-----------|------|
| **Raspberry Pi 5** | Decision engine -- runs Python FSM, vision, voice, expression, and GUI |
| **ESP32-S3** | Motor control, IR sensors (20 Hz), ultrasonic (10 Hz), NeoPixel LEDs, buzzer |
| **14" USB-C monitor** | Robot face (animated OLED eyes), camera feed, and debug dashboard via Pygame |

The Pi and ESP32 communicate over **UART at 115200 baud** (`/dev/ttyAMA2`). The Pi sends movement commands (`mv_vector:vx,vy,omega\n`) and the ESP32 sends sensor data back (`IR_STATUS:XX\n`, `DIST:XX.X\n`).

Mecanum inverse kinematics: `FL = vx+vy+omega`, `FR = vx-vy-omega`, `RL = vx-vy+omega`, `RR = vx+vy-omega`.

---

## Hardware

### Provided by HKU

- Raspberry Pi 5 + 5V/5A PSU + travel adapter + mobile battery pack + 64 GB SD
- ESP32-S3 mecanum car platform + 12V battery pack
- 3x long F-F wires (UART) + USB cable for ESP32 programming
- USB camera, USB microphone, USB speaker

### Purchased (additional)

- Micro-HDMI to HDMI cable 1 m (Pi 5 to monitor)
- 20000 mAh USB-C PD 65 W power bank (powers 14" monitor)
- USB-C to USB-C PD cable 1 m
- 4x SG90 9 g servos + mounting brackets (robot arm, PCA9685 ch1-4)
- LM2596 buck converter 12V to 5V 3A (servo power)
- HC-SR04 ultrasonic spare
- USB WiFi adapter RTL8811AU with external antenna
- USB 3.0 4-port powered hub
- M2/M2.5/M3 bolt+nut+allen key assortment kit

### On-robot peripherals

- SSD1306 128x64 OLED (I2C at 0x3C) -- animated eyes
- PCA9685 16-channel servo controller -- head tilt (ch0) + arm servos (ch1-4)
- 4x WS2812B NeoPixel LEDs (GPIO48)
- Piezo buzzer (GPIO46)
- HC-SR04 ultrasonic (GPIO4 trig, GPIO2 echo)
- 5x TCRT5000 IR line sensors (GPIO 5, 6, 7, 15, 45)

See `docs/WIRING.md` for the complete pin map.

---

## Software Setup

### Prerequisites

- Raspberry Pi OS (64-bit) on Pi 5
- Python 3.11+
- PlatformIO (for ESP32 firmware, built from Windows PC)

### Quick setup on the Pi

```bash
git clone https://github.com/Murathanx12/AR-2.git
cd AR-2
bash setup_pi.sh
```

This installs system packages (espeak-ng, portaudio, i2c-tools, mbrola), creates a Python venv, installs pip dependencies, and downloads the VOSK speech model.

### Manual setup

```bash
sudo apt-get install python3-venv python3-opencv espeak-ng portaudio19-dev mbrola mbrola-us1 i2c-tools
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Download the VOSK model manually if needed:

```bash
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip
```

### Optional: Claude API conversation (EC3)

```bash
pip install anthropic
export ANTHROPIC_API_KEY=your-key-here
```

### ESP32 firmware

From a Windows PC with PlatformIO installed:

```bash
cd esp32
pio run --target upload
```

---

## How to Run

```bash
source .venv/bin/activate

# Full GUI mode (default)
python3 Minilab5/alfred.py

# Headless mode (terminal dashboard, for SSH)
python3 Minilab5/alfred.py --headless

# Skip subsystems
python3 Minilab5/alfred.py --no-voice
python3 Minilab5/alfred.py --no-camera
python3 Minilab5/alfred.py --headless --no-voice --no-camera

# Override default speed (default: 35)
python3 Minilab5/alfred.py --speed 50

# Test individual subsystems
python3 Minilab5/alfred.py --test-vision
python3 Minilab5/alfred.py --test-voice

# Diagnose ESP32 connection
python3 scripts/test_esp32.py

# Run unit tests
python -m pytest tests/
```

---

## Voice Commands

**Wake phrase:** "Hello Sonny" (also accepts "hey sonny", "hi sonny", bare "hello")

Say the wake phrase once -- the robot stays awake until you say "sleep". All subsequent speech is treated as commands.

| Command | What it does |
|---------|-------------|
| `follow the track` / `follow line` / `follow path` | Start line following (R2) |
| `go to qr code` / `go to marker` / `find marker` | Search for and approach ArUco marker (R3) |
| `stop` / `halt` / `freeze` | Immediate stop (works from any state, even before wake) |
| `dance` / `groove` | 5-second dance routine with rainbow LEDs |
| `take photo` / `picture` / `selfie` | Capture and save a photo |
| `come here` / `come to me` | Approach the nearest detected person |
| `patrol` / `wander` / `explore` | Autonomous patrol with gesture recognition |
| `search` / `look around` / `scan` | Scan for ArUco markers by rotating |
| `chat` / `talk to me` / `tell me` | Start a Claude API conversation (EC3) |
| `sleep` / `rest` / `standby` | Go to sleep (requires wake phrase again) |

---

## Keyboard Controls (GUI mode)

| Key | Action |
|-----|--------|
| `W/A/S/D` | Forward / strafe left / reverse / strafe right |
| `Q/E` | Rotate left / rotate right |
| `M` | Toggle manual/auto mode |
| `F` | Start line following |
| `1/2` | Decrease / increase speed |
| `Space` | Emergency stop |
| `Esc` | Quit |

---

## Competition Requirements

| Req | Description | Status |
|-----|-------------|--------|
| **R1** | Voice commands -- wake phrase, FOLLOW TRACK, GO TO QR CODE | Done (VOSK STT + keyword matching) |
| **R2** | Line-following delivery -- IR sensors + weighted algorithm | Done (needs ESP32 hardware fix) |
| **R3** | ArUco marker approach -- visual-only with EMA smoothing | Done (needs ESP32) |
| **R4** | Obstacle detection -- HC-SR04 ultrasonic sensor | Done (needs ultrasonic wired) |
| **R5** | Intention indicators -- NeoPixel LEDs, TTS, buzzer, OLED eyes, GUI | Done |
| **EC1** | Gesture recognition -- MediaPipe, 6 gestures | Done |
| **EC3** | Claude API butler conversation (claude-haiku-4-5) | Done (needs ANTHROPIC_API_KEY) |
| **EC5** | Butler personality -- 8 emotions, animated eyes, head tracking | Done |

---

## Troubleshooting

**ESP32 motors not responding:**  
UART connects but motors don't spin. Suspected wiring/short/battery issue. Run `python3 scripts/test_esp32.py` to diagnose. Check 12V battery charge and motor driver connections.

**Voice recognition low accuracy (~50%):**  
VOSK small model struggles with accented English. Grammar-constrained recognition helps but is not perfect. Speak clearly within 30 cm of the USB mic. Consider using the phone app relay as an alternative.

**USB microphone weak pickup:**  
Only picks up from about 30 cm. A conference mic or phone relay (web app) works better for the demo.

**Camera not detected:**  
Run with `--no-camera` to skip. Check `ls /dev/video*` for available devices. Try `python3 Minilab5/alfred.py --test-vision` to test in isolation.

**No OLED display:**  
The eyes render in the GUI even without physical OLED hardware. Check I2C with `i2cdetect -y 1` (should show device at 0x3C).

**UART not connecting:**  
Verify wiring (Pi TX to ESP RX, Pi RX to ESP TX, common GND). Check that `/dev/ttyAMA2` exists. The Pi's UART must be enabled via `raspi-config`.

**No TTS audio:**  
Ensure `espeak-ng` is installed (`sudo apt install espeak-ng mbrola mbrola-us1`). Check that the USB speaker is the default ALSA output device.

---

## Project Structure

```
alfred/                     # Main Python package (runs on Pi)
  config.py                 # All tunable parameters as frozen dataclasses
  comms/
    protocol.py             # Pure UART command formatters
    uart.py                 # Thread-safe UART bridge (read/write)
  navigation/
    line_follower.py        # 6-state line following algorithm
    aruco_approach.py       # Visual-only ArUco approach with EMA smoothing
    obstacle_avoider.py     # Obstacle avoidance logic
    patrol.py               # Autonomous wander controller
  vision/
    camera.py               # Camera manager (USB or picamera2)
    aruco.py                # ArUco detection (DICT_4X4_50)
    obstacle.py             # Contour-based obstacle detection
    person.py               # MediaPipe face + hand + gesture detection
    bev.py                  # Bird's-eye view transform
    course_mapper.py        # Course mapping utilities
  voice/
    listener.py             # VOSK STT with grammar constraints + wake word
    intent.py               # Keyword-based intent classifier
    speaker.py              # TTS (piper-tts or espeak-ng fallback)
    conversation.py         # Claude API conversation engine (EC3)
  expression/
    eyes.py                 # OLED eye animation (8 emotions, gaze, blink)
    leds.py                 # NeoPixel LED patterns
    head.py                 # PCA9685 head servo control
    personality.py          # State-to-expression engine (10 Hz)
  fsm/
    states.py               # 17-state IntEnum definitions
    controller.py           # Main FSM dispatch loop (30 Hz)
  gui/
    debug_gui.py            # 1280x720 Pygame dashboard
  utils/
    logging.py              # Coloured console logging
    timing.py               # RateTimer, Stopwatch helpers
  web/                      # Phone app web relay (experimental)
Minilab5/
  alfred.py                 # Entry point
esp32/
  src/main.cpp              # ESP32-S3 firmware (PlatformIO)
docs/
  WIRING.md                 # Complete pin assignments
  ARCHITECTURE.md           # Architecture notes
scripts/
  test_esp32.py             # ESP32 connection diagnostics
  test_aruco.py             # ArUco detection test
  calibrate_bev.py          # Bird's-eye view calibration
tests/                      # pytest unit tests
setup_pi.sh                 # Automated Pi setup script
requirements.txt            # Python dependencies
```
