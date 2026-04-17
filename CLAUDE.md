Project
Sonny (Alfred V4) — Mecanum-wheeled robotic butler for HKU School of Innovation / Project Alfred.
Demo: April 24, 2026. Repo: https://github.com/Murathanx12/AR-2
Wake phrase: "Hello Sonny" (say once, stays awake until "sleep")

Known Issues (Apr 17, 2026)

1. ESP32 motors not responding — UART connects but motors don't spin. Suspected hardware (wiring/short/battery). Run scripts/test_esp32.py to diagnose.
2. USB microphone weak — only picks up from ~30cm. Threshold lowered to 1.5x noise floor. Need conference mic or phone relay for demo.
3. Obstacle detection disabled — camera-based detection had too many false positives. Only ultrasonic (when connected) triggers BLOCKED state.
4. MediaPipe not installed on Pi — person/gesture detection unavailable. Install: pip install mediapipe
5. OpenCV ArUco API — Pi has older OpenCV, code supports both old and new API. If ArUco fails, check cv2 version.
6. USB hub power — camera and mic must be plugged directly into Pi USB ports, NOT through the USB hub. WiFi adapter and speaker can stay on hub.

Architecture

ESP32-S3: Motor PWM + 5x IR sensor reading at 20Hz + HC-SR04 ultrasonic at 10Hz + NeoPixel LEDs + buzzer. Firmware: esp32/src/main.cpp (PlatformIO).
Raspberry Pi 5: Decision engine. Python. FSM + vision + voice + expression.
14" Type-C monitor: Robot face (OLED eyes) + camera feed + status GUI via Pygame.
UART: 115200 baud on /dev/ttyAMA2. Pi sends mv_vector:vx,vy,omega\n, ESP sends IR_STATUS:XX\n and DIST:XX.X\n.
Mecanum IK: FL=vx+vy+omega, FR=vx-vy-omega, RL=vx-vy+omega, RR=vx+vy-omega. PWM 50-200 from 0-100%.
Wiring: See docs/WIRING.md for complete pin map.

Network / VPN

- Windscribe VPN via OpenVPN (Singapore) — required for Claude API and Google STT in HK/China
- Config: /etc/openvpn/windscribe.conf, auth: /etc/openvpn/windscribe-auth.txt
- Connect: sudo openvpn --config /etc/openvpn/windscribe.conf --daemon
- Disconnect: sudo killall openvpn
- Verify: curl -s https://ipinfo.io/country (should show SG)
- Cloudflare WARP also installed but conflicts with Claude Code — use Windscribe instead

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

R1: Voice commands — wake phrase "Hello Sonny", FOLLOW TRACK, GO TO QR CODE. Google STT (primary) + Whisper tiny (offline fallback) + exact keyword matching. ✅ (code done, testing needed)
R2: Line-following delivery. IR sensors + weighted algorithmic control. ✅ (code done, needs ESP32 hardware fix)
R3: ArUco marker approach. Visual-only with EMA smoothing + simultaneous steer/drive. ✅ (code done, needs ESP32)
R4: Obstacle detection — ultrasonic HC-SR04 only (camera detection disabled — too many false positives). ✅ (code done, needs ultrasonic wired)
R5: Intention indicators — NeoPixel LEDs per state, TTS (piper/espeak-ng), buzzer, OLED eyes, 14" screen GUI. ✅
EC1: Gesture recognition — MediaPipe hands, 6 gestures, gesture→action in patrol. ✅ (needs mediapipe install)
EC3: Claude API butler conversation — claude-opus-4-6 with personality. ✅ (needs ANTHROPIC_API_KEY + VPN)
EC5: Butler personality — 8 emotions, animated eyes, head tracking. ✅

Voice System Design

- Primary STT: Google Speech Recognition (cloud, best accuracy for accented English, free API)
- Offline fallback: Whisper tiny (faster-whisper, ~80% accuracy) — auto-used when network fails
- Legacy fallback: VOSK grammar-constrained (if neither Google nor Whisper available)
- Energy-based VAD detects when you stop speaking, then transcribes complete utterance
- Noise calibration at startup — threshold = 1.5x ambient noise floor
- Wake word: "Hello Sonny" (also accepts "hello sunny", "hello sony", "hey sonny", bare "hello")
- Say wake word ONCE — robot stays awake. All subsequent speech = commands.
- "stop" always works from any state, even before wake word
- "sleep" requires wake word again
- Mic mutes during TTS to prevent echo loop (speaker → mic → false command)
- Intent classifier: exact keyword match only. No fuzzy, no confirmation dialogs.
- Install: pip install SpeechRecognition faster-whisper

Camera System

- USB camera auto-detected (scans indices 0-9, uses V4L2 backend to avoid GStreamer issues)
- Native resolution: 1920x1080 (set in config.py VisionConfig)
- Camera MUST be plugged directly into Pi USB port (not through hub — causes power/bandwidth issues)
- ArUco: DICT_4X4_50, supports both old and new OpenCV API

GUI System

- Pygame fullscreen GUI with --fullscreen flag (or F11 to toggle)
- Camera feed with ArUco/face/obstacle overlays
- Clickable command buttons as voice fallback (Wake Up, Follow Track, Dance, Stop, etc.)
- Keyboard controls: WASD=move, QE=turn, Space=emergency stop, M=mode, 1/2=speed
- Web dashboard also available at http://<pi-ip>:8080 with keyboard drive (WASD+QE+Space)

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

alfred/config.py — All params as frozen dataclasses. AlfredConfig singleton. Camera index auto-detected, resolution 1920x1080.
alfred/comms/ — protocol.py (pure cmd_* formatters), uart.py (UARTBridge, prints connection status).
alfred/navigation/ — line_follower.py (weighted algo), aruco_approach.py (visual-only + EMA smoothing), obstacle_avoider, patrol.
alfred/vision/ — camera (auto-detect V4L2), aruco (DICT_4X4_50, dual API), obstacle (contour), person (MediaPipe face+hand+gesture), BEV, course_mapper.
alfred/voice/ — listener.py (Google STT primary + Whisper fallback + VOSK, VAD, wake-once, mic mute), intent.py (exact keyword match), speaker.py (piper/espeak-ng TTS), conversation.py (Claude API EC3).
alfred/expression/ — eyes.py (8 emotions, gaze, auto-blink), leds.py (NeoPixel), head.py (PCA9685 servo), personality.py (state→expression, 10Hz).
alfred/fsm/ — states.py (17-state IntEnum), controller.py (30Hz dispatch, dance music via ffplay).
alfred/gui/ — debug_gui.py (Pygame fullscreen: eyes, camera+overlays, IR, vector, voice I/O, command buttons, event log).
alfred/web/ — app.py (Flask dashboard: live camera MJPEG, all sensors, voice I/O, keyboard drive WASD, event log).
alfred/utils/ — logging (colored), timing (RateTimer, Stopwatch).

Logging

- Detailed log files in logs/sonny_YYYYMMDD_HHMMSS.log
- All voice transcriptions, intent classifications, state transitions, errors logged with timestamps
- Send log file to Claude for debugging

Key Commands
```bash
# Connect VPN (required for Claude API / Google STT)
sudo openvpn --config /etc/openvpn/windscribe.conf --daemon

# Run Sonny V4 (on Raspberry Pi)
cd ~/AR-2 && source .venv/bin/activate
python3 Minilab5/alfred.py --fullscreen    # fullscreen GUI on Pi monitor
python3 Minilab5/alfred.py                 # windowed GUI
python3 Minilab5/alfred.py --headless      # terminal dashboard
python3 Minilab5/alfred.py --no-voice      # skip voice
python3 Minilab5/alfred.py --no-camera     # skip camera

# Build ESP32 firmware (from Windows PC)
cd esp32 && pio run --target upload

# Diagnose ESP32 connection
python3 scripts/test_esp32.py

# Run tests
python -m pytest tests/

# Test individual modules
python3 scripts/test_aruco.py
python3 scripts/calibrate_bev.py

# Read latest log
cat ~/AR-2/logs/$(ls -t ~/AR-2/logs/ | head -1)
```
