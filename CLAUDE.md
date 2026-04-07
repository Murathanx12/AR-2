Project
Sonny (Alfred V4) — Mecanum-wheeled robotic butler for HKU School of Innovation / Project Alfred coursework.
Demo: April 24, 2026. Repo: https://github.com/Murathanx12/AR-2
Wake phrase: "Hello Sonny"

Architecture

ESP32-S3: Motor PWM + 5x IR sensor reading at 20Hz. Firmware: src/main.cpp (PlatformIO).
Raspberry Pi 5: Decision engine. Python. FSM + vision + voice + expression.
UART: 115200 baud on /dev/ttyAMA2. Pi sends mv_vector:vx,vy,omega\n, ESP sends IR_STATUS:XX\n.
Mecanum IK: FL=vx+vy+omega, FR=vx-vy-omega, RL=vx-vy+omega, RR=vx+vy-omega. PWM 50-200 from 0-100%.

Current State

Minilab5/linefollower.py — Working V3 line follower (legacy, untouched). 6-state FSM, proportional omega steering, curve slowdown, Pygame GUI.
First in class for line following. Fastest manual time ~32s using diagonal mecanum driving.
V4 modular alfred/ package is live. Entry point: Minilab5/alfred.py.

V4 Modules

alfred/config.py — All params as frozen dataclasses. AlfredConfig singleton.
alfred/comms/ — protocol.py (pure cmd_* formatters), uart.py (UARTBridge thread-safe R/W).
alfred/navigation/ — line_follower.py (extracted V3 FSM), path_planner, aruco_approach, obstacle_avoider, patrol.
alfred/vision/ — camera, BEV, ArUco, obstacle, person detection, course_mapper. (stubs)
alfred/voice/ — listener (wake word), intent classifier (working keyword match), speaker/TTS. (stubs except intent)
alfred/expression/ — OLED eyes, NeoPixel LEDs, head servo, personality engine. (stubs)
alfred/fsm/ — states.py (17-state IntEnum), controller.py (AlfredFSM 30Hz dispatch loop).
alfred/gui/ — debug_gui.py (stub, use --headless or legacy V3).
alfred/utils/ — logging (colored), timing (RateTimer, Stopwatch).

Key Commands
```bash
# Build ESP32 firmware
pio run --target upload

# Run Sonny V4
python Minilab5/alfred.py
python Minilab5/alfred.py --headless --no-voice --no-camera

# Run legacy V3 line follower
python Minilab5/linefollower.py

# Run tests
python -m pytest tests/

# Test individual modules
python scripts/test_aruco.py
python scripts/calibrate_bev.py
```
