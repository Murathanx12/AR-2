Project
Sonny (Alfred V4) — Mecanum-wheeled robotic butler for HKU School of Innovation / Project Alfred coursework.
Demo: April 24, 2026. Repo: https://github.com/Murathanx12/AR-2
Wake phrase: "Hello Sonny"

Architecture

ESP32-S3: Motor PWM + 5x IR sensor reading at 20Hz + HC-SR04 ultrasonic at 10Hz + NeoPixel LEDs + buzzer. Firmware: esp32/src/main.cpp (PlatformIO).
Raspberry Pi 5: Decision engine. Python. FSM + vision + voice + expression.
UART: 115200 baud on /dev/ttyAMA2. Pi sends mv_vector:vx,vy,omega\n, ESP sends IR_STATUS:XX\n and DIST:XX.X\n.
Mecanum IK: FL=vx+vy+omega, FR=vx-vy-omega, RL=vx-vy+omega, RR=vx+vy-omega. PWM 50-200 from 0-100%.

Competition Requirements (Minilab 6 / Project Alfred)

R1: Voice commands — wake phrase "Hello Sonny", FOLLOW TRACK, GO TO QR CODE. VOSK STT. ✅
R2: Line-following delivery (from miniproject 2). IR sensors + PID. ✅
R3: Detect ArUco marker, navigate to it, stop without hitting. Visual-only approach. ✅
R4: Obstacle detection — ultrasonic HC-SR04, stop when path blocked during R2 and R3. ✅
R5: Intention indicators — NeoPixel LEDs per state, TTS announcements, buzzer on arrival. ✅
EC1: Gesture recognition — MediaPipe hands (stub ready).
EC3: Claude API butler conversation — alfred/voice/conversation.py. Needs ANTHROPIC_API_KEY. ✅
EC5: Butler personality — personality engine with expression system.

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

Current State

legacy/ — Old V1-V3 code (linefollower.py, advancedmovement.py, etc).
V4 modular alfred/ package is live. Entry point: Minilab5/alfred.py.

V4 Modules

alfred/config.py — All params as frozen dataclasses. AlfredConfig singleton.
alfred/comms/ — protocol.py (pure cmd_* formatters), uart.py (UARTBridge thread-safe R/W, parses IR+DIST).
alfred/navigation/ — line_follower.py (V3 FSM), aruco_approach.py (calibrated + visual-only), obstacle_avoider, patrol.
alfred/vision/ — camera, aruco (detect with center+size), obstacle, person detection, BEV, course_mapper.
alfred/voice/ — listener.py (VOSK STT), intent.py (keyword classifier), speaker.py (TTS), conversation.py (Claude API EC3).
alfred/expression/ — OLED eyes, NeoPixel LEDs, head servo, personality engine.
alfred/fsm/ — states.py (17-state IntEnum), controller.py (30Hz dispatch, R4 obstacle + R5 indicators).
alfred/gui/ — debug_gui.py (Pygame GUI).
alfred/utils/ — logging (colored), timing (RateTimer, Stopwatch).

Key Commands
```bash
# Build ESP32 firmware (from Windows PC)
cd esp32 && pio run --target upload

# Run Sonny V4 (on Raspberry Pi)
python Minilab5/alfred.py
python Minilab5/alfred.py --headless --no-voice --no-camera

# Run tests
python -m pytest tests/

# Test individual modules
python scripts/test_aruco.py
python scripts/calibrate_bev.py
```
