Project
Sonny (Alfred V4) — Mecanum-wheeled robotic butler for HKU School of Innovation / Project Alfred.
Demo: April 24, 2026. Repo: https://github.com/Murathanx12/AR-2
Wake phrase: "Hello Sonny" (say once, stays awake until "sleep")

Known Issues (Apr 15, 2026)

1. ESP32 motors not responding — UART connects but motors don't spin. Suspected hardware (wiring/short/battery). Run scripts/test_esp32.py to diagnose.
2. Voice recognition — upgraded to Whisper tiny (primary) with VOSK fallback. Install: pip install faster-whisper. Phone app on port 8080 as backup.
3. USB microphone weak — only picks up from ~30cm. Need conference mic or phone relay for demo.
4. Obstacle detection disabled — camera-based detection had too many false positives. Only ultrasonic (when connected) triggers BLOCKED state.

Architecture

ESP32-S3: Motor PWM + 5x IR sensor reading at 20Hz + HC-SR04 ultrasonic at 10Hz + NeoPixel LEDs + buzzer. Firmware: esp32/src/main.cpp (PlatformIO).
Raspberry Pi 5: Decision engine. Python. FSM + vision + voice + expression.
14" Type-C monitor: Robot face (OLED eyes) + camera feed + status GUI via Pygame.
UART: 115200 baud on /dev/ttyAMA2 (Pi GPIO4=TX pin7, GPIO5=RX pin29). Pi sends mv_vector:vx,vy,omega\n, ESP sends IR_STATUS:XX\n and DIST:XX.X\n.
IMPORTANT: Pi UART2 pins are GPIO4 (pin 7) and GPIO5 (pin 29), NOT GPIO14/GPIO15 (pins 8/10). Per INTC1002 Tutorial 3.
Mecanum IK: FL=vx+vy+omega, FR=vx-vy-omega, RL=vx-vy+omega, RR=vx+vy-omega. PWM 50-200 from 0-100%.
Wiring: See docs/WIRING.md for complete pin map.

Hardware Inventory

Provided by HKU:
- Raspberry Pi 5 + 5V/5A PSU + travel adapter + mobile battery pack + 64GB SD
- ESP32-S3 mecanum car platform + 12V battery pack
- 3x long F-F wires (UART) + USB cable for ESP32 programming
- USB camera, USB microphone, USB speaker

Purchased (additional):
- Micro-HDMI to HDMI cable 1m (Pi 5 → monitor)
- 20000mAh USB-C PD 65W power bank (powers 14" monitor)
- USB-C to USB-C PD cable 1m
- 4x SG90 9g servos + mounting brackets (robot arm, PCA9685 ch1-4)
- LM2596 buck converter 12V→5V 3A (servo power from battery)
- HC-SR04 ultrasonic spare
- USB WiFi adapter RTL8811AU with external antenna
- USB 3.0 4-port powered hub
- M2/M2.5/M3 bolt+nut+allen key assortment kit

On-robot peripherals:
- SSD1306 128x64 OLED (I2C @ 0x3C) — animated eyes
- PCA9685 16-channel servo controller — head tilt (ch0) + arm servos (ch1-4)
- 4x WS2812B NeoPixel LEDs (GPIO48)
- Piezo buzzer (GPIO46)
- HC-SR04 ultrasonic (GPIO4 trig, GPIO2 echo)
- 5x TCRT5000 IR line sensors (GPIO 5,6,7,15,45)

Competition Requirements (Minilab 6 / Project Alfred)

R1: Voice commands — wake phrase "Hello Sonny", FOLLOW TRACK, GO TO QR CODE. VOSK STT + exact keyword matching. ✅ (code done, accuracy needs improvement)
R2: Line-following delivery. IR sensors + weighted algorithmic control. ✅ (code done, needs ESP32 hardware fix)
R3: ArUco marker approach. Visual-only with EMA smoothing + simultaneous steer/drive. ✅ (code done, needs ESP32)
R4: Obstacle detection — ultrasonic HC-SR04 only (camera detection disabled — too many false positives). ✅ (code done, needs ultrasonic wired)
R5: Intention indicators — NeoPixel LEDs per state, TTS (espeak-ng), buzzer, OLED eyes, 14" screen GUI. ✅
EC1: Gesture recognition — MediaPipe hands, 6 gestures, gesture→action in patrol. ✅
EC3: Claude API butler conversation — claude-haiku-4-5 with personality. ✅ (needs ANTHROPIC_API_KEY)
EC5: Butler personality — 8 emotions, animated eyes, head tracking. ✅

Voice System Design

- Primary STT: Whisper tiny (faster-whisper, ~80% accuracy, handles accents well)
- Fallback STT: VOSK grammar-constrained (if Whisper not installed)
- Energy-based VAD detects when you stop speaking, then transcribes complete utterance
- Wake word: "Hello Sonny" (also accepts "hello sunny", "hello sony", "hey sonny", bare "hello")
- Say wake word ONCE — robot stays awake. All subsequent speech = commands.
- "stop" always works from any state, even before wake word
- "sleep" requires wake word again
- Mic mutes during TTS to prevent echo loop (speaker → mic → false command)
- Intent classifier: exact keyword match only. No fuzzy, no confirmation dialogs.
- Phone web controller (port 8080) as backup — uses phone's browser STT for best accuracy
- Install Whisper: pip install faster-whisper (downloads ~75MB tiny.en model on first run)
- Install VOSK fallback: pip install vosk + download vosk-model-small-en-us-0.15

UART Protocol (Pi → ESP32)

mv_fwd:speed, mv_rev:speed, mv_left:speed, mv_right:speed
mv_turnleft:speed, mv_turnright:speed, mv_spinleft:speed, mv_spinright:speed
mv_sidepivot:frontSpeed,rearPercent,direction
mv_curve:leftSpeed,rightSpeed
mv_vector:vx,vy,omega
stop:0
led:r,g,b (NeoPixel color)
led_pattern:id (0=solid, 1=pulse, 2=rainbow, 3=blink, 4=breathe)
buzzer:freq,duration_ms

UART Protocol (ESP32 → Pi)

IR_STATUS:XX (5-bit sensor mask, 20Hz)
DIST:XX.X (ultrasonic cm, 10Hz)

V4 Modules

alfred/config.py — All params as frozen dataclasses. AlfredConfig singleton.
alfred/comms/ — protocol.py (pure cmd_* formatters), uart.py (UARTBridge, prints connection status).
alfred/navigation/ — line_follower.py (weighted algo), aruco_approach.py (visual-only + EMA smoothing), obstacle_avoider, patrol.
alfred/vision/ — camera, aruco (DICT_4X4_50), obstacle (contour), person (MediaPipe face+hand+gesture), BEV, course_mapper.
alfred/voice/ — listener.py (Whisper tiny primary + VOSK fallback, VAD, wake-once, mic mute), intent.py (exact keyword match), speaker.py (espeak-ng TTS), conversation.py (Claude API EC3).
alfred/expression/ — eyes.py (8 emotions, gaze, auto-blink), leds.py (NeoPixel), head.py (PCA9685 servo), personality.py (state→expression, 10Hz).
alfred/fsm/ — states.py (17-state IntEnum), controller.py (30Hz dispatch).
alfred/gui/ — debug_gui.py (1280x720 Pygame: eyes, camera+overlays, IR, vector, voice I/O, gestures, event log).
alfred/utils/ — logging (colored), timing (RateTimer, Stopwatch).

Key Commands
```bash
# Build ESP32 firmware (from Windows PC)
cd esp32 && pio run --target upload

# Run Sonny V4 (on Raspberry Pi)
python3 Minilab5/alfred.py              # full GUI
python3 Minilab5/alfred.py --headless   # terminal dashboard
python3 Minilab5/alfred.py --no-voice   # skip voice
python3 Minilab5/alfred.py --no-camera  # skip camera

# Diagnose ESP32 connection
python3 scripts/test_esp32.py

# Run tests
python -m pytest tests/

# Test individual modules
python3 scripts/test_aruco.py
python3 scripts/calibrate_bev.py
```
