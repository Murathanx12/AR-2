# Sonny V4 — Architecture & Module Documentation

## Table of Contents

1. [System Overview](#system-overview)
2. [Module Reference](#module-reference)
3. [Communication Protocol](#communication-protocol)
4. [Threading Model](#threading-model)
5. [Graceful Degradation](#graceful-degradation)
6. [Version Evolution Deep Dive](#version-evolution-deep-dive)
7. [ESP32 Firmware](#esp32-firmware)

---

## System Overview

Sonny is a split-brain robot:

- **ESP32-S3** — Low-level real-time control: motor PWM, IR sensor reading at 20Hz, command parsing
- **Raspberry Pi 5** — High-level decision-making: FSM, vision pipeline, voice recognition, expression

They communicate over UART at 115200 baud. The Pi sends movement commands, the ESP32 sends sensor data.

### Data Flow

```
                    ┌─────────────────────────────────────────────────────┐
                    │                  Raspberry Pi 5                     │
                    │                                                     │
 Camera ──────────►│  CameraManager ──► ArucoDetector ──► ArucoApproach │
                    │        │          ObstacleDetector  ObstacleAvoider│
                    │        │          PersonDetector    PatrolController│
                    │        │          BirdEyeView       PathPlanner    │
                    │        ▼                                           │
                    │  ┌─────────────────────────────────┐               │
                    │  │        AlfredFSM (30Hz)          │               │
                    │  │  IDLE → LISTEN → FOLLOW → ...    │               │
                    │  │  tick() dispatches per state     │               │
                    │  └──────────┬──────────────────────┘               │
                    │             │                                       │
 Mic ─► Whisper ──►│  VoiceListener ──► IntentClassifier                │
                    │                                                     │
                    │  PersonalityEngine ──► EyeController (OLED)       │
                    │                    ──► LEDController (NeoPixel)    │
                    │                    ──► HeadController (Servo)      │
                    │                    ──► Speaker (TTS)               │
                    │             │                                       │
                    │             ▼                                       │
                    │  UARTBridge ◄─────────── LineFollower              │
                    │      │                   cmd_vector/cmd_stop        │
                    └──────┼─────────────────────────────────────────────┘
                           │ UART 115200
                    ┌──────┼─────────────────────────┐
                    │      ▼        ESP32-S3          │
                    │  Command Parser                  │
                    │      │                           │
                    │  vectorDrive(vx, vy, omega)      │
                    │      │                           │
                    │  FL = vx+vy+omega (Motor A)     │
                    │  FR = vx-vy-omega (Motor B)     │
                    │  RL = vx-vy+omega (Motor C)     │
                    │  RR = vx+vy-omega (Motor D)     │
                    │                                  │
                    │  5x IR → IR_STATUS:XX (20Hz) ──►│
                    └──────────────────────────────────┘
```

---

## Module Reference

### alfred/config.py

**Purpose:** Single source of truth for all tunable parameters.

Uses frozen dataclasses so parameters are immutable at runtime. The module-level `CONFIG` singleton provides global access:

```python
from alfred.config import CONFIG

speed = CONFIG.speed.default_speed      # 35
gain = CONFIG.curve.omega_gain          # 4.5
port = CONFIG.uart.port                 # '/dev/ttyAMA2'
wake = CONFIG.voice.wake_phrase         # 'Hello Sonny'
```

**Dataclass hierarchy:**
- `SensorConfig` — IR sensor order, lost delay, turn/move strength arrays
- `SpeedConfig` — min/max/default speed, accel/decel rates
- `CurveConfig` — omega gain, sweep turn speed, slowdown factor/exponent
- `RecoveryConfig` — reverse/pivot speeds, pseudo-distance thresholds
- `ParkingConfig` — delivery zone timing and speed
- `UARTConfig` — serial port and baud rate
- `VoiceConfig` — wake phrase, Whisper model, Piper voice
- `VisionConfig` — camera index, resolution, ArUco dict, BEV points
- `ExpressionConfig` — OLED address/size, NeoPixel pin/count, servo channel/range

### alfred/comms/protocol.py

**Purpose:** Pure functions that format UART command strings. No side effects, no I/O.

```python
cmd_vector(30, 0, 15)  →  "mv_vector:30,0,15\n"
cmd_stop()             →  "stop:0\n"
cmd_side_pivot(80, 15, 1)  →  "mv_sidepivot:80,15,1\n"
```

10 functions total: `cmd_vector`, `cmd_stop`, `cmd_forward`, `cmd_reverse`, `cmd_strafe_left`, `cmd_strafe_right`, `cmd_turn_left`, `cmd_turn_right`, `cmd_curve`, `cmd_side_pivot`.

### alfred/comms/uart.py — UARTBridge

**Purpose:** Thread-safe serial communication with the ESP32.

- `open()` — Opens serial port, starts daemon reader thread. If pyserial isn't installed or port unavailable, enters dry-run mode (no errors, just logs warning)
- `send(command)` — Writes command string to serial
- `get_ir_bits()` — Returns `[W, NW, N, NE, E]` as 5-element list of 0/1
- `get_ir_status()` — Returns raw 5-bit integer
- `_reader_loop()` — Daemon thread that reads `IR_STATUS:XX` lines and sends periodic pings

### alfred/navigation/line_follower.py — LineFollower

**Purpose:** The V3 line-following algorithm, extracted from the monolith.

**6-state FSM (FollowState enum):**

1. **FOLLOWING** — Normal tracking. Computes `turn_var` from weighted sensor fusion, applies curve slowdown, outputs `(vx, 0, omega)`. If all sensors lose the line for 1.2s, enters LOST_REVERSE. Actively sweeps in last turn direction while searching.

2. **ENDPOINT** — All 5 sensors ON. Monitors for delivery zone (sustained >0.4s). If sensors clear, returns to FOLLOWING. If pseudo-distance exceeded, stops.

3. **PARKING** — Creeps forward at parking speed for `drive_time` seconds, then sets `finished=True`.

4. **LOST_REVERSE** — Backs up at `recovery.reverse_speed` until pseudo-distance threshold or line reappears, then enters LOST_PIVOT.

5. **LOST_PIVOT** — Pivots via `cmd_side_pivot` in last turn direction until a sensor with acceptable turn_var is found.

6. **STOPPED** — Decelerates to zero, sends stop command.

**Usage:**
```python
follower = LineFollower(speed=35)
bits = uart.get_ir_bits()
command = follower.tick(bits)  # returns "mv_vector:30,0,15\n"
uart.send(command)
```

### alfred/navigation/path_planner.py — PathPlanner

**Purpose:** Pure pursuit controller — follows a path spline using lookahead targeting.

Given a numpy array of (x,y) path points and current robot pose (x, y, theta):
1. Finds closest point on spline
2. Selects lookahead point ahead on the spline
3. Computes angle error to lookahead
4. Outputs (vx, 0, omega) with curvature-based speed scaling

Also provides `fuse_with_ir()` to blend vision-planned velocities with IR corrections.

### alfred/navigation/aruco_approach.py — ArucoApproach

**Purpose:** Proportional controller for approaching ArUco markers.

From the marker's translation vector (tx, ty, tz from camera):
- `vx` = proportional to depth (tz), with slowdown near arrival
- `vy` = proportional to lateral offset (tx), strafes to centre
- `omega` = proportional to bearing angle, rotates to face

`is_arrived(tvec)` returns True when distance < `arrival_distance` (default 5cm).

### alfred/navigation/obstacle_avoider.py — ObstacleAvoider

**Purpose:** Repulsive potential field for reactive obstacle avoidance.

Each obstacle generates a repulsive force inversely proportional to distance. Forces are summed and converted to:
- Negative vx (slow down)
- Lateral vy (strafe away)
- Omega (rotate away)

### alfred/navigation/patrol.py — PatrolController

**Purpose:** Random wandering with person detection trigger.

Changes direction at random intervals (`turn_interval` = 3s). Biases away from obstacles. When `persons` list is non-empty, `should_approach_person()` returns True to trigger FSM transition.

### alfred/vision/camera.py — CameraManager

**Purpose:** OpenCV VideoCapture wrapper.

`open()` → `read_frame()` → `close()`. Sets resolution and FPS. `is_available` property checks if capture is active. Returns None safely when OpenCV not installed.

### alfred/vision/bev.py — BirdEyeView

**Purpose:** Perspective transform for top-down view.

1. `calibrate(src_points, dst_points)` — Computes transform matrix from 4 point pairs
2. `transform(frame)` — Warps camera image to bird's-eye view
3. `extract_path(bev)` — Adaptive thresholds the BEV to find the dark line, extracts centroids per row
4. `fit_spline(pts)` — Fits a degree-3 polynomial through path points

### alfred/vision/aruco.py — ArucoDetector

**Purpose:** ArUco marker detection using OpenCV's `cv2.aruco` module.

- `detect(frame)` — Returns list of `{"id": int, "corners": ndarray(4,2)}`
- `estimate_pose(marker)` — Returns `{"tvec": [...], "rvec": [...]}` (requires camera calibration)
- `compute_approach_vector(pose)` — Converts pose to (vx, vy, omega) using proportional control

### alfred/vision/obstacle.py — ObstacleDetector

**Purpose:** Contour-based obstacle detection in camera frames.

Analyzes the bottom 60% of the frame (ROI), converts to HSV, thresholds for dark objects, finds contours above minimum area. Returns sorted list by area.

`is_path_clear(frame)` checks if any obstacle is in the centre strip.

### alfred/vision/person.py — PersonDetector

**Purpose:** MediaPipe-powered face and hand detection.

- `detect_faces(frame)` — Returns bounding boxes and confidence scores
- `detect_hands(frame)` — Returns 21-point hand landmarks
- `get_gesture(hand)` — Classifies gesture from finger positions: fist, open, thumbs_up, peace, point, wave

### alfred/vision/course_mapper.py — CourseMapper

**Purpose:** Build a track map from accumulated BEV frames.

1. `start_scan()` → `add_frame(frame, pose)` repeatedly → `build_map()`
2. Stitches frames using affine transforms based on robot pose (x, y, theta)
3. Extracts waypoints from the largest track contour

### alfred/voice/listener.py — VoiceListener

**Purpose:** Background voice listening with Whisper transcription.

Runs a daemon thread that records 3-second audio chunks via `sounddevice`, checks RMS for silence, transcribes with Whisper, and checks for wake word ("Hello Sonny"). Calls registered callback with transcribed text.

### alfred/voice/intent.py — IntentClassifier

**Purpose:** Keyword-based intent classification.

Maps 8 intents to keyword lists. `classify(text)` returns `(intent_name, confidence)`. First keyword match wins. Returns `("unknown", 0.0)` for no match.

### alfred/voice/speaker.py — Speaker

**Purpose:** Text-to-speech with auto-detected engine.

Tries piper → espeak-ng → espeak → print fallback. Non-blocking `say()` runs in a thread. `play_sound(name)` and `play_music(path)` use pygame.mixer. 13 predefined butler phrases.

### alfred/expression/eyes.py — EyeController

**Purpose:** Animated eye display for OLED.

Renders eye shapes to a PIL Image based on current emotion. 8 emotions with different shapes (width, height, roundness, eyebrow offset). Features:
- Gaze tracking (look_at x,y)
- Auto-blink every 4 seconds
- Blink animation (0.3s close-open)
- Pupils that follow gaze
- Heart decorations for "love" emotion
- Pushes to SSD1306 OLED if connected

### alfred/expression/leds.py — LEDController

**Purpose:** NeoPixel LED ring control.

10 state colours mapped to FSM states. Threaded animations:
- `pulse(color, duration)` — sine-wave brightness
- `rainbow_cycle(speed, duration)` — rotating HSV rainbow

Falls back to internal colour tracking without hardware.

### alfred/expression/head.py — HeadController

**Purpose:** Servo-based head tilt.

- `set_tilt(angle)` — Direct angle control (clamped to range)
- `nod(amplitude, count, speed)` — Up-down animation
- `shake(amplitude, count, speed)` — Left-right animation
- `look_at_person(face)` — Maps face bbox to servo angle

### alfred/expression/personality.py — PersonalityEngine

**Purpose:** Coordinates all expression subsystems per FSM state.

Maps each of the 17 FSM states to an emotion, LED state, and head position. Updates all subsystems each tick. Tracks faces for gaze. Announces state changes via speaker.

### alfred/fsm/controller.py — AlfredFSM

**Purpose:** The brain. Coordinates everything.

**Initialization:** Creates all subsystems (UART, line follower, vision, voice, expression) with try/except for each. Missing hardware = None.

**30Hz tick loop:**
1. Read camera frame (shared across states)
2. Dispatch to state handler (`_tick_idle`, `_tick_following`, etc.)
3. Update personality engine

**State handlers (all 17 implemented):**
- `_tick_idle` — Wait for wake word
- `_tick_listening` — Listening for voice command
- `_tick_following` — Run line follower, check obstacles, mirror sub-FSM
- `_tick_aruco_search` — Rotate slowly scanning for markers
- `_tick_aruco_approach` — Proportional drive toward marker
- `_tick_blocked` — Stop, check if path clears
- `_tick_rerouting` — Compute avoidance manoeuvre
- `_tick_patrol` — Wander + detect people
- `_tick_person_approach` — Drive toward largest face
- `_tick_dancing` — 6-move timed dance pattern with rainbow LEDs
- `_tick_photo` — Capture frame, save JPEG
- `_tick_sleeping` — Listen for wake word to wake up

---

## Communication Protocol

### Pi → ESP32 (Commands)

```
mv_vector:30,0,15\n     Mecanum drive: vx=30 forward, vy=0, omega=15 CW
mv_sidepivot:80,15,1\n  Pivot: 80% front, 15% rear, direction=1 (right)
mv_fwd:50\n              Forward at 50%
stop:0\n                 Emergency stop
```

### ESP32 → Pi (Sensor Data)

```
IR_STATUS:12\n           5-bit bitmask: bit0=W, bit1=NW, bit2=N, bit3=NE, bit4=E
Hello from ESP32\n       Heartbeat (every 1.5s)
```

IR_STATUS example: `12` = binary `01100` = NW and N sensors active.

---

## Threading Model

```
Main Thread (30Hz)           UART Reader (daemon)        Voice Listener (daemon)
┌──────────────────┐        ┌─────────────────────┐     ┌──────────────────┐
│ FSM tick loop    │        │ serial.readline()   │     │ Record 3s chunk  │
│ Vision pipeline  │        │ Parse IR_STATUS     │     │ Check silence    │
│ GUI rendering    │        │ Update ir_status    │     │ Whisper transcribe│
│ Expression update│        │   (with lock)       │     │ Check wake word  │
│ Send commands    │        │ Send pings          │     │ Call on_speech() │
└──────────────────┘        └─────────────────────┘     └──────────────────┘
         │                          │                           │
         └──── shared state ────────┘                           │
              (ir_lock)                                         │
         └──── callback ────────────────────────────────────────┘
              (_on_voice_command)
```

Animation threads (LED pulse, rainbow, head nod/shake) run as short-lived daemon threads.

---

## Graceful Degradation

Every hardware dependency uses conditional imports:

```python
try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False
```

| Missing | Impact | Fallback |
|---------|--------|----------|
| pyserial | No UART | Dry-run mode (commands logged, IR returns zeros) |
| opencv-python | No vision | Camera returns None, detectors return empty lists |
| mediapipe | No person detection | detect_faces/hands return [] |
| sounddevice | No voice input | Listener.start() is a no-op |
| whisper | No transcription | All audio ignored |
| piper/espeak | No TTS | Text printed to console |
| PIL | No eye rendering | Internal state tracked, no display |
| neopixel | No LEDs | Colour state tracked internally |
| adafruit-servokit | No head servo | Angle tracked internally |
| pygame | No GUI | Use --headless mode |

---

## Version Evolution Deep Dive

### The Steering Problem

The core challenge across all versions: **how to steer a mecanum robot along a line.**

**V1 tried differential steering:**
```
left_speed = base - turn_correction
right_speed = base + turn_correction
```
Problem: On sharp curves, one side goes too slow or reverses, causing jerky movement.

**V2 tried PID + strafe:**
```
P = Kp × error
I = Ki × Σerror (with anti-windup)
D = Kd × Δerror
omega = P + I + D
vy = small_strafe_correction  # lateral slide for fine adjustment
```
Problem: PID is smooth on gentle curves but overshoots on sharp turns. The strafe component fights with rotation on tight corners. Hard to tune 3 PID gains + strafe gain + speed adaptation simultaneously.

**V3 found the answer: just slow down:**
```
omega = OMEGA_GAIN × turn_var  # simple proportional
vx = base_speed × curve_slowdown(turn_ratio)  # power curve
vy = 0  # no strafe ever
```
Insight: A robot that crawls at 20% speed through sharp curves while rotating hard will always stay on the line. No PID needed — the slowdown gives it time to react.

### The Recovery Problem

**V1:** Reverse a fixed distance, then pivot. Problem: fixed distance sometimes not enough, sometimes too much.

**V2:** Pseudo-distance integration (`speed × dt`). Better: reverses proportionally to how fast it was going. Added side-pivot command for rear-axle rotation.

**V3:** Added sweep-turn: actively rotates while searching instead of just coasting. Time-based lost detection (1.2s) prevents false triggers. The `has_seen_line` flag prevents recovery at startup when sensors haven't found the line yet.

### The Delivery Zone Problem

**V1:** No delivery zone handling.

**V2:** All 5 sensors ON → must be a junction or delivery zone. But junctions also trigger all-5-ON briefly. Solution: require sustained all-ON for 0.4 seconds. Short blip = junction (drive through), long hold = delivery zone (park).

**V3/V4:** Same logic, proven reliable. Parking sequence: detect zone → creep forward at 15% speed for 0.8s → full stop.
