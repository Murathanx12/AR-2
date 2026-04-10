# Project Alfred — Setup, Testing & Troubleshooting Guide

**Robot:** Sonny (Artooth chassis, ESP32-S3 + Raspberry Pi 5, mecanum wheels)
**Demo Date:** April 24, 2026
**Wake Phrase:** "Hello Sonny"

---

## 1. Hardware Wiring

### ESP32-S3 Pin Map

| Component | Pin | GPIO | Notes |
|-----------|-----|------|-------|
| Motor A (FL) | DIR1/DIR2 | 3, 10 | Left front |
| Motor B (FR) | DIR1/DIR2 | 11, 12 | Right front |
| Motor C (RL) | DIR1/DIR2 | 13, 14 | Left rear |
| Motor D (RR) | DIR1/DIR2 | 21, 47 | Right rear |
| IR Sensor W | Digital IN | 5 | Far left |
| IR Sensor NW | Digital IN | 6 | Northwest |
| IR Sensor N | Digital IN | 7 | Center front |
| IR Sensor NE | Digital IN | 15 | Northeast |
| IR Sensor E | Digital IN | 45 | Far right |
| Ultrasonic TRIG | Digital OUT | 4 | HC-SR04 trigger |
| Ultrasonic ECHO | Digital IN | 2 | HC-SR04 echo (**needs voltage divider!**) |
| NeoPixel Data | Digital OUT | 48 | WS2812B data line |
| Buzzer | Digital OUT | 46 | Passive buzzer |
| UART RX (from Pi) | Serial | 16 | Pi TX → ESP32 RX |
| UART TX (to Pi) | Serial | 17 | ESP32 TX → Pi RX |

### Ultrasonic Voltage Divider (IMPORTANT)

The HC-SR04 echo pin outputs 5V but ESP32 GPIO is 3.3V. Use a voltage divider:

```
ECHO PIN ──[1kΩ]──┬──[2kΩ]── GND
                   │
                   └── ESP32 GPIO2
```

### Raspberry Pi 5 Connections

| Connection | Port | Notes |
|-----------|------|-------|
| USB Camera | USB 3.0 (blue) | Higher bandwidth |
| USB Microphone | USB 2.0 (black) | Any USB mic |
| Speaker | 3.5mm jack or USB | For TTS output |
| ESP32 UART | /dev/ttyAMA2 | TX→GPIO16, RX→GPIO17 on ESP32 |

---

## 2. Software Setup

### 2.1 ESP32 Firmware

```bash
# From project root on your development machine
cd ~/PlatformIO/Projects/alfred

# Build and upload firmware
pio run --target upload

# Monitor serial output (for debugging)
pio device monitor
```

The firmware now handles:
- Motor commands (same as before)
- IR sensor broadcast at 20Hz (`IR_STATUS:XX`)
- Ultrasonic distance broadcast at 10Hz (`DIST:XX.X`)
- NeoPixel LED control (`led:r,g,b` and `led_pattern:id`)
- Buzzer control (`buzzer:freq,duration_ms`)

### 2.2 Raspberry Pi Setup

```bash
# Clone the repo
git clone https://github.com/Murathanx12/AR-2.git
cd AR-2

# Run the setup script (installs all dependencies + VOSK model)
chmod +x setup_pi.sh
./setup_pi.sh

# Activate virtual environment
source .venv/bin/activate
```

### 2.3 Manual Setup (if setup_pi.sh fails)

```bash
# System packages
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip python3-opencv \
    libatlas-base-dev i2c-tools espeak-ng portaudio19-dev ffmpeg \
    mbrola mbrola-us1

# Python venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# VOSK model (REQUIRED for voice commands)
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip
rm vosk-model-small-en-us-0.15.zip
```

### 2.4 Optional: Claude API Conversation (EC3)

```bash
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-your-key-here"
```

---

## 3. Running the Robot

### Full Mode (with GUI, voice, camera)
```bash
python Minilab5/alfred.py
```

### Headless Mode (no display)
```bash
python Minilab5/alfred.py --headless
```

### Without Voice (for testing without mic)
```bash
python Minilab5/alfred.py --no-voice
```

### Without Camera (for testing without camera)
```bash
python Minilab5/alfred.py --no-camera
```

### Legacy Line Follower (V3, for comparison)
```bash
python Minilab5/linefollower.py
```

---

## 4. Testing Checklist

### R1 — Voice Commands (10%)
- [ ] Say **"Hello Sonny"** → robot acknowledges, LEDs turn bright blue, enters LISTENING state
- [ ] Say **"Follow track"** → enters FOLLOWING state, LEDs turn green, TTS says "Following the track"
- [ ] Say **"Go to QR code"** → enters ARUCO_SEARCH, LEDs turn yellow, TTS says "Searching for the marker"
- [ ] Say **"Stop"** → enters STOPPING, motors stop, LEDs turn red
- [ ] Say **"Sleep"** → enters SLEEPING, LEDs off, TTS says "Going to sleep"
- [ ] Silence for 5 seconds while LISTENING → times out back to IDLE
- [ ] Verify VOSK recognises commands reliably in demo environment noise

### R2 — Line Following Delivery (10%)
- [ ] Place robot on black line track
- [ ] Trigger via voice or GUI → follows line smoothly
- [ ] Handles curves at reasonable speed
- [ ] Handles intersections (goes straight)
- [ ] Detects endpoint and stops
- [ ] TTS announces "I have arrived at the destination" + buzzer beep

### R3 — ArUco Navigation (10%)
- [ ] Print ArUco marker (4x4_50 dictionary, any ID, at least 10cm)
- [ ] Trigger via "Go to QR code" voice command
- [ ] Robot spins slowly to find marker (yellow LEDs, breathe pattern)
- [ ] When found: LEDs turn orange, TTS says "Marker found. Approaching"
- [ ] Robot centers marker in camera view then drives toward it
- [ ] Slows down as marker gets bigger in frame
- [ ] Stops within 15-30cm without hitting marker
- [ ] TTS announces arrival + buzzer beep
- [ ] Works without camera calibration (visual-only mode)

### R4 — Obstacle Detection (10%)
- [ ] During line follow: place hand/object <20cm in front → robot stops
- [ ] LEDs turn red and blink
- [ ] TTS says "Obstacle detected. Please clear the path"
- [ ] Remove obstacle → TTS says "Path clear. Resuming" → robot resumes
- [ ] During ArUco approach: same obstacle test
- [ ] During ArUco search: obstacle stops spinning
- [ ] Verify ultrasonic readings are stable (no false positives)
- [ ] Test with objects at various distances (10cm, 20cm, 30cm)

### R5 — Intention Indicators (10%)
- [ ] **LED Colors match states:**
  - IDLE = dim blue
  - LISTENING = bright blue
  - FOLLOWING = green
  - ARUCO_SEARCH = yellow (breathing animation)
  - ARUCO_APPROACH = orange
  - BLOCKED = red (blinking)
  - DANCING = rainbow
  - SLEEPING = off (dim breathe)
- [ ] **TTS announces every state transition**
- [ ] **Buzzer beeps on arrival** (line follow end, ArUco reached, person reached)
- [ ] A bystander can understand what the robot is doing without explanation

### EC3 — Claude API Conversation (5%)
- [ ] Set ANTHROPIC_API_KEY environment variable
- [ ] Say "Hello Sonny" then "chat" or "tell me"
- [ ] Robot responds with butler-style natural language via TTS
- [ ] Conversation maintains context across exchanges
- [ ] Falls back to canned responses when WiFi unavailable

### Full Integration Flow
- [ ] Power on → blue LED, TTS "Good day, I am Sonny"
- [ ] "Hello Sonny" → bright blue, "I'm listening"
- [ ] "Follow track" → green, follows line → arrives → beep, announces
- [ ] "Hello Sonny" → "Go to QR code" → searches → approaches → arrives → beep
- [ ] Place obstacle during any task → stops → clears → resumes
- [ ] "Stop" → immediate stop
- [ ] "Sleep" → LEDs off → "Hello Sonny" wakes up

---

## 5. Common Problems & Solutions

| Problem | Likely Cause | Solution |
|---------|-------------|----------|
| **Camera not found** | USB 3.0 not recognized | Replug camera, check `ls /dev/video*`, try `cv2.VideoCapture(0)` then `(1)` |
| **VOSK model not found** | Model directory missing | Download: `wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip` |
| **VOSK crashes on start** | Wrong model path | Place model folder in working directory or set `vosk_model_path` in config |
| **Voice commands not recognised** | Background noise / wrong words | Speak clearly, closer to mic. Commands must match VOSK grammar exactly |
| **"Hello Sonny" not detected** | Phrase must be exactly "hello sonny" | Say both words clearly with brief pause. VOSK is case-insensitive |
| **ArUco not detected** | Bad lighting / small marker | Print marker larger (>10cm), ensure good lighting, check `python scripts/test_aruco.py` |
| **Robot overshoots ArUco** | Approach speed too high | Reduce `approach_speed` in ArucoApproach or increase `stop_size` in config |
| **Ultrasonic gives -1** | No echo (wiring issue) | Check TRIG/ECHO pins, verify voltage divider on ECHO, test with `pio device monitor` |
| **Ultrasonic false positives** | Reflective surfaces or noise | Add 3-reading averaging, increase threshold from 20cm to 25cm |
| **UART timeout / no response** | Wrong serial port | Run `ls /dev/ttyAMA*` and update `UARTConfig.port` in config.py |
| **UART shows garbled text** | Baud rate mismatch | Both Pi and ESP32 must be 115200. Check `monitor_speed` in platformio.ini |
| **espeak-ng no sound** | Wrong audio device | Run `aplay -l` to list devices, set `AUDIODEV=hw:X,0` env var |
| **Motors jitter at low speed** | PWM below minimum | MIN_PWM is 50 in firmware. Don't send speed < 5 from Pi |
| **LEDs not lighting** | Wrong GPIO or wiring | Check NeoPixel data pin (GPIO48), ensure common ground with ESP32 |
| **LED command ignored** | Old firmware | Reflash ESP32 with updated main.cpp: `pio run --target upload` |
| **Buzzer silent** | Wrong pin or passive buzzer | GPIO46 with passive buzzer needs `tone()`. Active buzzer just needs HIGH/LOW |
| **Robot drifts during line follow** | Mecanum slippage / sensor alignment | Adjust `turn_strengths` in config.py, check sensor mounting |
| **Claude API errors** | Missing API key or no WiFi | Set `ANTHROPIC_API_KEY` env var, check internet: `ping api.anthropic.com` |
| **Import errors on Pi** | Missing packages | Re-run `pip install -r requirements.txt` in the venv |
| **Permission denied on serial** | User not in dialout group | `sudo usermod -aG dialout $USER` then reboot |

---

## 6. Architecture Overview

### State Machine Flow
```
          [IDLE] ←──── "stop" / timeout
            │
            │ "Hello Sonny"
            ▼
        [LISTENING] ──── 5s timeout ──→ [IDLE]
            │
     ┌──────┴──────┐
     │              │
"follow track"  "go to qr code"
     │              │
     ▼              ▼
[FOLLOWING]    [ARUCO_SEARCH] ──spin──→ marker found
     │              │                       │
     │              └───────────────────────┘
     │                                      │
     │                                      ▼
     │                              [ARUCO_APPROACH]
     │                                      │
     │         close enough ────────────────┘
     │              │
     ▼              ▼
  [arrived]     [arrived]
  beep+TTS      beep+TTS
     │              │
     └──────┬───────┘
            ▼
          [IDLE]

  ANY MOVING STATE ──obstacle──→ [BLOCKED] ──cleared──→ resume previous
```

### File Structure
```
alfred/
├── config.py              # All tunable parameters
├── comms/
│   ├── protocol.py        # UART command formatters
│   └── uart.py            # Thread-safe serial bridge
├── fsm/
│   ├── states.py          # 17-state IntEnum
│   └── controller.py      # Main FSM + R4/R5 integration
├── navigation/
│   ├── line_follower.py   # V3 line following FSM
│   ├── aruco_approach.py  # Calibrated + visual-only approach
│   ├── obstacle_avoider.py
│   └── patrol.py
├── vision/
│   ├── camera.py          # OpenCV capture manager
│   ├── aruco.py           # ArUco detect + center/size
│   ├── obstacle.py        # Camera-based obstacle detection
│   ├── person.py          # Face/hand detection
│   ├── bev.py             # Bird's eye view transform
│   └── course_mapper.py   # Map building
├── voice/
│   ├── listener.py        # VOSK STT + wake word
│   ├── intent.py          # Keyword intent classifier
│   ├── speaker.py         # TTS (espeak-ng/piper)
│   └── conversation.py    # Claude API butler chat (EC3)
├── expression/
│   ├── personality.py     # State → expression mapping
│   ├── eyes.py            # OLED eye animations
│   ├── leds.py            # NeoPixel controller
│   └── head.py            # Servo head tilt
├── gui/
│   └── debug_gui.py       # Pygame debug GUI
└── utils/
    ├── logging.py         # Colored logging
    └── timing.py          # Rate timer, stopwatch
```

---

## 7. Tuning Guide

### Line Following Speed
Edit `alfred/config.py` → `SpeedConfig.default_speed`. Start at 35, increase to 50+ after testing.

### ArUco Stop Distance
Edit `alfred/config.py` → `VisionConfig.aruco_stop_size`. Default 150 pixels. Increase to stop further away, decrease to get closer.

### Obstacle Threshold
Edit `alfred/config.py` → `UltrasonicConfig.threshold_cm`. Default 20cm. Increase if getting false positives.

### Camera Resolution
Edit `alfred/config.py` → `VisionConfig.resolution`. Default (800, 600). Lower to (640, 480) if frame rate drops.

### Voice Recognition Sensitivity
If VOSK misrecognises, edit the grammar in `alfred/voice/listener.py` → `VoiceListener.GRAMMAR`. Fewer words = better accuracy.

---

## 8. Demo Day Checklist

### Morning Setup
- [ ] Charge battery / connect power supply
- [ ] Flash ESP32 firmware: `pio run --target upload`
- [ ] Boot Pi, activate venv: `source .venv/bin/activate`
- [ ] Verify camera: `python scripts/test_aruco.py`
- [ ] Verify audio: `espeak-ng "Testing audio"`
- [ ] Verify UART: check serial monitor for `IR_STATUS` and `DIST` messages
- [ ] Print ArUco markers (4x4_50, at least 10cm, multiple IDs)
- [ ] Set up the line track

### Pre-Demo Test Run
- [ ] Run `python Minilab5/alfred.py`
- [ ] Test full flow: wake → follow track → arrive → wake → go to QR → arrive
- [ ] Test obstacle stop during both modes
- [ ] Verify all LED states are visible
- [ ] Verify TTS is audible in demo room

### During Demo
- [ ] Start alfred.py before demo begins
- [ ] Keep terminal visible for debug output
- [ ] Have a backup plan: `python Minilab5/linefollower.py` if V4 fails
- [ ] Keep ArUco markers handy at various positions
