Project
Sonny (Alfred V4) — Mecanum-wheeled robotic butler for HKU School of Innovation / Project Alfred.
Demo: April 24, 2026. Repo: https://github.com/Murathanx12/AR-2
Wake phrase: "Hello Sonny" (say once, stays awake until "sleep")

Known Issues (Apr 20, 2026)

1. ESP32 motors not responding — UART connects but motors don't spin. Suspected hardware (wiring/short/battery). Run scripts/test_esp32.py to diagnose. CRITICAL for demo.
2. USB microphone weak — only picks up from ~30cm. WORKAROUND: use phone as wireless mic via web dashboard (http://<pi-ip>:8080, hold-to-talk button).
3. Obstacle detection — YOLO (offline, primary) + ultrasonic HC-SR04 (when wired). OpenAI Vision scene analyzer is opt-in via `--vision-ai` flag (off by default to save API budget).
4. MediaPipe not installed on Pi — person/gesture detection unavailable. Install: pip install mediapipe
5. OpenCV ArUco API — Pi has older OpenCV, code supports both old and new API. If ArUco fails, check cv2 version.
6. USB hub power — camera and mic must be plugged directly into Pi USB ports, NOT through the USB hub.
7. VPN not auto-starting — run `sudo openvpn --config /etc/openvpn/windscribe.conf --daemon` each boot, or set up systemd service (see below).

Architecture

ESP32-S3: Motor PWM + 5x IR sensor reading at 20Hz + HC-SR04 ultrasonic at 10Hz + NeoPixel LEDs + buzzer. Firmware: esp32/src/main.cpp (PlatformIO).
Raspberry Pi 5: Decision engine. Python. FSM + vision + voice + expression.
14" Type-C monitor: Demo face (large animated eyes + status bar) via Pygame `--demo` mode. Debug GUI via default mode.
UART: 115200 baud on /dev/ttyAMA2. Pi sends mv_vector:vx,vy,omega\n, ESP sends IR_STATUS:XX\n and DIST:XX.X\n.
Mecanum IK: FL=vx+vy+omega, FR=vx-vy-omega, RL=vx-vy+omega, RR=vx+vy-omega. PWM 50-200 from 0-100%.
Wiring: See docs/WIRING.md for complete pin map.

**Direction convention (critical — get this right or everything drives backwards):**
- `vx > 0` = forward, `vx < 0` = reverse
- `vy > 0` = strafe right, `vy < 0` = strafe left
- `omega > 0` = spin **right** (CW viewed from above), `omega < 0` = spin left
- Convention is proved by line-follower's `turn_strengths = (-7, -4.5, 0, +4.5, +7)` for sensors `(W, NW, N, NE, E)`: line under E (rightmost sensor) → positive turn_var → positive omega → spin right to chase. Every other controller (ArucoApproach, person-follow, obstacle_avoider, patrol) must use the same sign.
- To **centre a target visible at error_x** (where error_x > 0 = target in right half of frame): `omega = +K * error_x`. A minus sign here spins the robot AWAY from its target — this bug has bitten the codebase twice, once in person-follow and once in the ArUco back-up branch (both fixed 2026-04-20, commits `fcf10dc` / `16d2652`).

Network / VPN

- Windscribe VPN via OpenVPN (Singapore) — required for OpenAI API, Claude API, and Google STT in HK/China
- Config: /etc/openvpn/windscribe.conf, auth: /etc/openvpn/windscribe-auth.txt
- Connect: sudo openvpn --config /etc/openvpn/windscribe.conf --daemon
- Disconnect: sudo killall openvpn
- Verify: curl -s https://ipinfo.io/country (should show SG)
- Auto-start: sudo systemctl enable openvpn@windscribe (or create custom systemd service)

API Keys

- Store in `.env` file at project root (already in .gitignore)
- OPENAI_API_KEY — for Whisper STT, GPT-4o-mini intent classification, and Vision scene analysis
- ANTHROPIC_API_KEY — optional, not currently used (conversation uses OpenAI GPT-4o-mini)
- Budget: ~$25 on OpenAI. Whisper=$0.006/min, GPT-4o-mini=$0.15/1M input. Enough for weeks of testing.
- All modules auto-load from .env via python-dotenv

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
- SSD1306 128x64 OLED (I2C @ 0x3C) — animated eyes (also rendered large on 14" monitor in demo mode)
- PCA9685 16-channel servo controller — head tilt (ch0) + left arm (ch1-2) + right arm (ch3-4)
- 4x WS2812B NeoPixel LEDs (GPIO48)
- Piezo buzzer (GPIO46)
- HC-SR04 ultrasonic (GPIO4 trig, GPIO2 echo)
- 5x TCRT5000 IR line sensors (GPIO 5,6,7,15,45)

Servo Arm Layout (PCA9685):
- ch0: Head tilt (up/down)
- ch1: Left shoulder (perpendicular mount, rotates arm up/down)
- ch2: Left elbow (tilt)
- ch3: Right shoulder
- ch4: Right elbow
- Arms are cosmetic — wave on greeting, carry pose during delivery, dance moves, shrug when blocked

Competition Requirements (Minilab 6 / Project Alfred)

R1: Voice commands — wake phrase "Hello Sonny", FOLLOW TRACK, GO TO QR CODE. OpenAI Whisper API (primary) + Google STT (fallback) + GPT-4o-mini smart intent classification. ✅
R2: Line-following delivery. IR sensors + weighted algorithmic control. ✅ (needs ESP32 hardware fix)
R3: ArUco marker approach (1-50). Visual-only with EMA smoothing. Say "go to marker 5" or any number 1-50. ✅ (needs ESP32)
R4: Obstacle detection — ultrasonic HC-SR04 + OpenAI Vision scene analyzer for smart understanding. ✅ (needs ultrasonic wired)
R5: Intention indicators — NeoPixel LEDs per state, TTS (piper/espeak-ng), buzzer, OLED eyes, 14" demo face GUI, arm gestures. ✅
EC1: Gesture recognition — MediaPipe hands, 6 gestures, gesture→action in patrol. ✅ (needs mediapipe install)
EC2: Autonomous rerouting — obstacle_avoider.py potential field. ✅ (basic)
EC3: OpenAI GPT-4o-mini butler conversation. Unknown intents auto-routed to chat. Low-confidence intents ask to rephrase. ✅ (needs OPENAI_API_KEY + VPN)
EC4: Autonomous patrol — random wander + person detection + gesture recognition. ✅
EC5: Butler personality — 8 emotions, animated eyes on 14" screen, arm servos, head tracking. ✅

Voice System Design

- Primary STT: OpenAI Whisper API (cloud, best accuracy, handles noise/accents, $0.006/min)
- Fallback 1: Google Speech Recognition (cloud, free, good accuracy)
- Fallback 2: Whisper tiny (offline, faster-whisper, ~80% accuracy)
- Fallback 3: VOSK grammar-constrained (if nothing else works)
- Smart intent: GPT-4o-mini classifies natural language into intents + extracts marker IDs 1-50
- Keyword fallback: longest-match keyword classifier (works offline)
- Energy-based VAD detects when you stop speaking, then transcribes complete utterance
- Noise calibration at startup — threshold = 1.5x ambient noise floor
- Wake word: "Hello Sonny" (also accepts "hello sunny", "hello sony", "hey sonny", bare "hello")
- Say wake word ONCE — robot stays awake. All subsequent speech = commands.
- "stop" always works from any state, even before wake word
- "sleep" requires wake word again
- Mic mutes during TTS to prevent echo loop
- Unknown intents auto-routed to OpenAI GPT-4o-mini conversation engine
- Low-confidence intents (< 70%) ask "Did you mean X?" instead of blindly executing
- Phone mic relay: web dashboard has hold-to-talk button, streams audio to Pi for transcription
- Install: pip install openai python-dotenv SpeechRecognition faster-whisper

Camera System

- USB camera auto-detected (scans indices 0-9, uses V4L2 backend to avoid GStreamer issues)
- **Capture: 1280×720 @ 24 fps, MJPG fourcc** (set in `config.py :: VisionConfig`). YUYV uncompressed at 1080p saturated USB 2.0 and locked the FSM to ~10 fps; MJPG at 720p comfortably sustains 24 fps+ with ArUco detect running ~20 ms/frame. `CameraManager.actual_fps` is logged every ~5 s.
- Camera MUST be plugged directly into Pi USB port (not through hub)
- ArUco: DICT_4X4_50 markers 0-49, supports both old and new OpenCV API
- **ArUco approach is distance-based, not pixel-size-based.** `ArucoApproach._distance_m(pixel_size, frame_width)` uses the pinhole model with `PHYSICAL_MARKER_M = 0.05` (5 cm printed tag) and `FOCAL_RATIO = 0.8` (≈ focal_length_px / frame_width for typical USB webcams). Stop target: `STOP_DIST_M = 0.20` (20 cm), hold band 0.15–0.30 m, re-engage beyond 0.35 m. Tune `PHYSICAL_MARKER_M` if your printed marker isn't 5 cm; tune `FOCAL_RATIO` after measuring a known distance if the stop point is consistently off.
- Max reliable ArUco detection range at 720p ≈ 2 m for a 5 cm marker; 3 m at 1080p. Detection *accuracy* (when detected) is the same at both resolutions — it's binary.
- OpenAI Vision scene analyzer: periodic AI-powered scene understanding during patrol/search states
- Person detection: MediaPipe face + hand + 6 gestures (when installed)

ArUco approach with camera-based obstacle avoidance

- During `ARUCO_APPROACH` and `ARUCO_SEARCH`, every tick runs two independent obstacle checks:
  1. **Ultrasonic** (`_check_ultrasonic_obstacle`) — hard emergency stop at < 20 cm, transitions to `BLOCKED` (stop-and-wait). Only active when HC-SR04 is wired; returns False otherwise.
  2. **Camera** (`_check_camera_obstacle`) — YOLO centre-path-clear check (primary) with contour-based `ObstacleDetector` fallback. If something blocks the centre of the frame, transitions to `REROUTING` (strafe around).
- `REROUTING` is a **three-phase manoeuvre** so the camera always faces the direction of motion (no blind sideways strafes). Sub-FSM in `_tick_rerouting`:
  1. `turn_away` — rotate in place to push the obstacle to the far frame edge. Obstacle on right half → `omega=-25` (rotate left, CCW; obstacle drifts right off-screen). Left half → `omega=+25`. Done when obstacle cx is past the 15 % / 85 % edge, is no longer detected, or 1.8 s elapse.
  2. `drive_around` — `vx=25, vy=0, omega=0` moving forward with the camera leading. Exits after the path stays clear for ~5 consecutive frames *and* a minimum drive time of 0.8 s has passed (prevents peek-past false exits), or on a 3 s per-phase timeout. If a new obstacle appears mid-drive, falls back to `turn_away` with a freshly-chosen rotation direction.
  3. `turn_back` — rotate the **opposite** direction looking for the target marker. If the marker reappears → straight back to `ARUCO_APPROACH`. On 2.5 s timeout → hand off to `ARUCO_SEARCH` which further biases the spin by `_aruco_last_cx`.
- Overall 8 s timeout across all three phases; says "I cannot find a way around" and goes to `IDLE` if it fires. Ultrasonic always preempts to `BLOCKED`.
- **Marker memory** (`_remember_marker`): every time the target marker is detected in ARUCO_SEARCH, ARUCO_APPROACH, or REROUTING, we cache `_aruco_last_cx` / `_aruco_last_size` / `_aruco_last_frame_w` / `_aruco_last_seen_time`. When `_tick_aruco_search` has no marker in the current frame, it biases its rotation toward the last-known bearing: `omega = -8` if the marker was in the left half of the frame, else `+8`. Memory expires after 10 s.
- On a fresh `go to marker N` voice command, `transition()` clears both the bearing memory and the reroute state so a new target doesn't inherit stale data. "Stop" intent also clears reroute state.
- **Limitation (known):** the ultrasonic is forward-facing, so while strafing sideways we have no side collision sensing. User plans to add 3 ultrasonic sensors later for surround coverage. Until then REROUTING can scrape a side obstacle — the 6 s timeout is the safety net.

Person-follow behavior (FSM state `PERSON_APPROACH`, intent `come_here` / "follow me")

- Uses MediaPipe face detection. Largest face = closest person.
- Stop condition is resolution-independent: face width ≥ 25 % of frame width (≈ half a metre for an adult head).
- EMA smoothing (α=0.4) on face centre and width so detection jitter doesn't whip the heading.
- Same omega convention as everything else: face on right → +omega → spin right.
- Lost on a single frame → rotate-and-scan at omega=8 up to 4 s, then give up and return to IDLE with "I seem to have lost you." Does NOT fall through to PATROL.
- Once reached, robot stays with the person and keeps heading locked. If they walk away, size_frac drops and the approach resumes. Greeting plays only once per command.

GUI System

- Debug mode (default): Pygame dashboard with camera feed, eyes, sensors, command buttons, event log
- Demo mode (--demo): Fullscreen animated robot face for the 14" monitor
  - Large animated eyes with 8 emotions, gaze tracking, auto-blink
  - Mouth animation (smile, frown, surprised O, neutral line)
  - Status bar showing current state + voice transcript + intent
  - Camera PiP in corner with ArUco overlay
  - Rainbow border effect during dance
  - Press ESC to quit, F11 to toggle fullscreen
- Keyboard controls: WASD=move, QE=turn, Space=STOP, M=mode, 1/2=speed, F11=fullscreen
- Web dashboard: http://<pi-ip>:8080 with phone mic relay, keyboard drive, all sensors

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
alfred/comms/ — protocol.py (pure cmd_* formatters), uart.py (UARTBridge, thread-safe).
alfred/navigation/ — line_follower.py (weighted algo, 6-state sub-FSM), aruco_approach.py (visual EMA), obstacle_avoider.py (potential field), patrol.py (wander + person detect), path_planner.py (pure pursuit).
alfred/vision/ — camera.py (auto-detect V4L2), aruco.py (DICT_4X4_50, dual API), yolo_detector.py (YOLOv8n offline object detection, primary), obstacle.py (contour fallback), person.py (MediaPipe face+hand+gesture), scene_analyzer.py (GPT-4o-mini vision, backup), bev.py, course_mapper.py.
alfred/voice/ — listener.py (OpenAI API primary + Google + Whisper + VOSK, VAD, wake-once, mic mute), intent.py (GPT-4o-mini smart + keyword fallback), speaker.py (piper/espeak-ng TTS), conversation.py (GPT-4o-mini butler chat).
alfred/expression/ — eyes.py (8 emotions, OLED + GUI), leds.py (NeoPixel), head.py (PCA9685 ch0), arms.py (PCA9685 ch1-4, cosmetic animations), personality.py (state→expression, 10Hz).
alfred/fsm/ — states.py (17-state IntEnum), controller.py (30Hz dispatch, integrates all subsystems).
alfred/gui/ — debug_gui.py (Pygame debug dashboard), demo_gui.py (fullscreen robot face for 14" monitor).
alfred/web/ — app.py (Flask dashboard: camera MJPEG, sensors, voice, keyboard drive, phone mic relay).
alfred/utils/ — logging (colored), timing (RateTimer, Stopwatch).

Logging

- Detailed log files in logs/sonny_YYYYMMDD_HHMMSS.log
- All voice transcriptions, intent classifications, state transitions, errors logged with timestamps
- Send log file to Claude for debugging

Key Commands
```bash
# Connect VPN (required for all cloud APIs)
sudo openvpn --config /etc/openvpn/windscribe.conf --daemon

# Run Sonny V4 (on Raspberry Pi)
cd ~/AR-2 && source .venv/bin/activate
python3 Minilab5/alfred.py --demo --fullscreen  # demo face on 14" monitor
python3 Minilab5/alfred.py --fullscreen          # debug GUI fullscreen
python3 Minilab5/alfred.py                       # windowed debug GUI
python3 Minilab5/alfred.py --headless            # terminal dashboard (SSH)
python3 Minilab5/alfred.py --no-voice            # skip voice
python3 Minilab5/alfred.py --no-camera           # skip camera
python3 Minilab5/alfred.py --vision-ai           # enable OpenAI Vision (5s interval)
python3 Minilab5/alfred.py --vision-ai --vision-ai-interval 1.0  # test mode (1s)

# Build ESP32 firmware (from Windows PC)
cd esp32 && pio run --target upload

# Diagnose ESP32 connection
python3 scripts/test_esp32.py

# Run tests
python -m pytest tests/

# Test individual modules
python3 scripts/test_aruco.py
python3 scripts/test_whisper.py
python3 scripts/test_tts.py

# Read latest log
cat ~/AR-2/logs/$(ls -t ~/AR-2/logs/ | head -1)

# Install new dependencies
pip install openai python-dotenv
```

Dependencies (install on Pi)
```bash
pip install openai python-dotenv     # OpenAI API + env loading
pip install ultralytics              # YOLOv8 offline object detection
pip install SpeechRecognition        # Google STT
pip install faster-whisper           # Offline Whisper fallback
pip install mediapipe                # Person/gesture detection (EC1)
pip install flask                    # Web dashboard
pip install anthropic                # Claude conversation (EC3)
pip install pyaudio                  # Microphone input
pip install pygame                   # GUI
pip install opencv-python-headless   # Vision
pip install Pillow                   # Eye rendering
```
