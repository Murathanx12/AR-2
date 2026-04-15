Project
Sonny (Alfred V4) — Mecanum-wheeled robotic butler for HKU School of Innovation / Project Alfred coursework.
Demo: April 24, 2026. Repo: https://github.com/Murathanx12/AR-2
Wake phrase: "Hello Sonny" (EN) / "Merhaba Sonny" (TR)

Architecture

ESP32-S3: Motor PWM + 5x IR sensor reading at 20Hz + HC-SR04 ultrasonic at 10Hz + NeoPixel LEDs + buzzer. Firmware: esp32/src/main.cpp (PlatformIO).
Raspberry Pi 5: Decision engine. Python. FSM + vision + voice + expression.
14" Type-C monitor: Robot face (OLED eyes scaled up) + camera feed + status GUI via Pygame.
UART: 115200 baud on /dev/ttyAMA2. Pi sends mv_vector:vx,vy,omega\n, ESP sends IR_STATUS:XX\n and DIST:XX.X\n.
Mecanum IK: FL=vx+vy+omega, FR=vx-vy-omega, RL=vx-vy+omega, RR=vx+vy-omega. PWM 50-200 from 0-100%.

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

R1: Voice commands — wake phrase, FOLLOW TRACK, GO TO QR CODE. VOSK STT + fuzzy intent matching. ✅
R2: Line-following delivery. IR sensors + weighted algorithmic control. ✅
R3: ArUco marker approach. Visual-only with temporal smoothing + simultaneous steer/drive. ✅
R4: Obstacle detection — ultrasonic HC-SR04 + camera contour detection, dual-sensor gate. ✅
R5: Intention indicators — NeoPixel LEDs per state, TTS announcements, buzzer, OLED eyes on 14" screen. ✅
EC1: Gesture recognition — MediaPipe hands, 6 gestures (fist/open/thumbs_up/peace/point/wave), gesture→action in patrol. ✅
EC3: Claude API butler conversation — claude-haiku-4-5 with butler personality. ✅
EC5: Butler personality — personality engine, 8 emotions, animated eyes, head tracking, multilingual TTS. ✅

Language Support

English (default): VOSK en-US model, espeak-ng mb-us1 voice
Turkish (optional): VOSK tr model (vosk-model-small-tr-0.3), espeak-ng Turkish voice
Switch at runtime: say "switch language to Turkish" / "speak Turkish" / "dil degistir"

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
alfred/comms/ — protocol.py (pure cmd_* formatters), uart.py (UARTBridge thread-safe R/W, parses IR+DIST).
alfred/navigation/ — line_follower.py (weighted algo), aruco_approach.py (visual-only + calibrated, EMA smoothing), obstacle_avoider, patrol.
alfred/vision/ — camera, aruco (DICT_4X4_50, detect+draw+pose), obstacle (contour-based), person (MediaPipe face+hand+gesture), BEV, course_mapper.
alfred/voice/ — listener.py (VOSK STT, EN+TR, runtime switching), intent.py (fuzzy keyword classifier), speaker.py (multilingual TTS), conversation.py (Claude API EC3).
alfred/expression/ — eyes.py (8 emotions, gaze tracking, auto-blink), leds.py (NeoPixel animations), head.py (PCA9685 servo), personality.py (state→expression, 10Hz update).
alfred/fsm/ — states.py (17-state IntEnum), controller.py (30Hz dispatch, R4 obstacle + R5 indicators + EC1 gestures).
alfred/gui/ — debug_gui.py (1024x600 Pygame dashboard: OLED eyes, camera with overlays, IR sensors, vector field, status log, gesture display).
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
