# Sonny — Mecanum Robotic Butler

> A modular mecanum-wheeled robot with line following, computer vision, voice control, and expressive personality. Built with ESP32-S3 + Raspberry Pi 5 for HKU School of Innovation.

[![PlatformIO](https://img.shields.io/badge/PlatformIO-ESP32--S3-orange?logo=platformio)](https://platformio.org/)
[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)](https://python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](#license)

*Named after Sonny from I, Robot — the robot who develops emotions and free will.*

---

## What Sonny Can Do

- **Follow lines** — 5-sensor IR array with proportional steering and curve slowdown
- **See** — Camera with ArUco marker detection, obstacle avoidance, person/gesture recognition
- **Listen** — Wake word ("Hello Sonny") + Whisper speech-to-text + intent classification
- **Speak** — Piper TTS with butler personality phrases
- **Express** — OLED animated eyes (8 emotions), NeoPixel LED ring, head servo gestures
- **Navigate** — 17-state FSM: patrol, approach people, dance, take photos, deliver packages
- **Drive omnidirectionally** — Mecanum wheels: forward, strafe, rotate, and any combination

---

## Architecture

```
Raspberry Pi 5                              ESP32-S3
┌─────────────────────────────┐    UART    ┌──────────────────────┐
│  alfred/ Python package     │◄─────────►│  Motor Control (PWM) │
│  ├── FSM Controller (30Hz)  │  115200    │  5x IR Sensor (20Hz) │
│  ├── Vision Pipeline        │   baud     │  Mecanum IK          │
│  ├── Voice (Whisper + TTS)  │            │  Command Parser      │
│  ├── Expression Engine      │            └──────────────────────┘
│  └── Pygame Debug GUI       │                     │
└─────────────────────────────┘              IR_STATUS:XX (20Hz)
        │                                   mv_vector:vx,vy,omega
   Camera  Mic  OLED  LEDs  Servo
```

### Hardware

```
       [N]    <- center front IR sensor
      /   \
   [NW]   [NE]  <- diagonal IR sensors
   /         \
 [W]         [E]  <- side IR sensors
  |    [CAM]   |
  A --------- B   <- front mecanum wheels
  |   [OLED]   |
  C --------- D   <- rear mecanum wheels
      [LED]
```

| Component | Details |
|-----------|---------|
| **MCU** | ESP32-S3-DevKitM-1 |
| **SBC** | Raspberry Pi 5 |
| **Motors** | 4x mecanum wheel motors (PWM 50-200) |
| **IR Sensors** | 5x line sensors on GPIO 5, 6, 7, 15, 45 |
| **Camera** | USB/CSI camera (640x480 @ 30fps) |
| **Display** | SSD1306 OLED 128x64 (I2C) — animated eyes |
| **LEDs** | NeoPixel 12-LED ring (GPIO 18) |
| **Servo** | Head tilt servo via PCA9685 |
| **Audio** | USB microphone + speaker |
| **Communication** | UART at 115200 baud (`/dev/ttyAMA2`) |

---

## Project Structure

```
sonny/
├── alfred/                        # V4 Python package
│   ├── config.py                  # All parameters as frozen dataclasses
│   ├── comms/
│   │   ├── protocol.py            # Command formatters (cmd_vector, cmd_stop, ...)
│   │   └── uart.py                # Thread-safe serial bridge with IR parsing
│   ├── navigation/
│   │   ├── line_follower.py       # V3 line-following FSM (extracted from monolith)
│   │   ├── path_planner.py        # Pure pursuit velocity planner
│   │   ├── aruco_approach.py      # Proportional ArUco marker approach
│   │   ├── obstacle_avoider.py    # Repulsive potential field avoidance
│   │   └── patrol.py              # Random wander with person detection
│   ├── vision/
│   │   ├── camera.py              # OpenCV camera manager
│   │   ├── bev.py                 # Bird's-eye-view perspective transform
│   │   ├── aruco.py               # ArUco detection + 6-DOF pose estimation
│   │   ├── obstacle.py            # Contour-based obstacle detection
│   │   ├── person.py              # MediaPipe face/hand/gesture detection
│   │   └── course_mapper.py       # Track mapping from accumulated BEV frames
│   ├── voice/
│   │   ├── listener.py            # Whisper STT with wake-word detection
│   │   ├── intent.py              # Keyword intent classifier (8 intents)
│   │   └── speaker.py             # Piper/espeak TTS with butler phrases
│   ├── expression/
│   │   ├── eyes.py                # OLED eye animation (8 emotions + gaze)
│   │   ├── leds.py                # NeoPixel state colours + animations
│   │   ├── head.py                # Servo tilt with nod/shake/tracking
│   │   └── personality.py         # Coordinates all expression by FSM state
│   ├── fsm/
│   │   ├── states.py              # 17-state IntEnum
│   │   └── controller.py          # Main FSM with 30Hz dispatch loop
│   ├── gui/
│   │   └── debug_gui.py           # Pygame dashboard (sensor, vector, camera)
│   └── utils/
│       ├── logging.py             # Colored console logger
│       └── timing.py              # RateTimer + Stopwatch
├── Minilab5/
│   ├── alfred.py                  # V4 entry point (GUI + headless + test modes)
│   └── linefollower.py            # V3 legacy monolith (untouched, still works)
├── src/main.cpp                   # ESP32-S3 firmware (PlatformIO/Arduino)
├── scripts/                       # Calibration and test scripts
├── tests/                         # pytest unit tests (23 tests)
├── legacy/                        # V1 and V2 archived code
├── assets/                        # Sounds, eye frames, dance routines
├── requirements.txt               # Python dependencies
├── setup_pi.sh                    # Raspberry Pi setup script
└── platformio.ini                 # ESP32 build configuration
```

---

## Quick Start

### ESP32 Firmware

```bash
pip install platformio
pio run --target upload
```

### Raspberry Pi

```bash
# Full setup (first time)
bash setup_pi.sh

# Or manual install
pip install -r requirements.txt

# Run Sonny V4 (with GUI)
python Minilab5/alfred.py

# Run headless (no display)
python Minilab5/alfred.py --headless

# Run without specific hardware
python Minilab5/alfred.py --no-voice --no-camera

# Run legacy V3 line follower
python Minilab5/linefollower.py

# Run tests
python -m pytest tests/ -v
```

### Test Individual Subsystems

```bash
python Minilab5/alfred.py --test-vision    # Camera + ArUco + face detection
python Minilab5/alfred.py --test-voice     # Wake word + STT + TTS
python scripts/calibrate_camera.py         # Camera intrinsic calibration
python scripts/calibrate_bev.py            # Bird's-eye-view point selection
python scripts/test_aruco.py               # Live ArUco marker overlay
python scripts/test_oled_eyes.py           # Cycle eye emotions
python scripts/test_leds.py               # NeoPixel animation test
```

---

## Version History — The Evolution of Sonny

### V1: The First Steps (March 23-24, 2026)

**The problem:** Make a mecanum robot follow a black line on a white surface.

**What we built:**
- 5 IR sensors arranged in a semicircular arc (W, NW, N, NE, E) — upgraded from an initial 3-sensor design
- ESP32 reads sensors at 20Hz, broadcasts `IR_STATUS:XX` over UART
- Pi runs weighted sensor fusion: each sensor has a turn strength value, the weighted sum gives a steering direction
- Movement used differential steering: `mv_curve:left,right` with different speeds per side

**How V1 steered:**
```
Turn direction = (W × -7) + (NW × -4.5) + (N × 0) + (NE × +4.5) + (E × +7)
                 ─────────────────────────────────────────────────────────────
                              number of active sensors
```
If the line is under the E sensor, turn_var = +7 (turn hard right). Under N = 0 (go straight).

**V1 commands:** `mv_fwd`, `mv_rev`, `mv_left`, `mv_right`, `mv_turnleft`, `mv_turnright`, `mv_curve`, `stop`

**Recovery:** When all sensors lose the line → reverse a bit → pivot in the last known turn direction.

**Results:** Could follow gentle curves but struggled with sharp turns. Lost the line frequently on tight corners. Noisy lost-detection triggered false recovery.

**Key learnings:**
- 5 sensors >> 3 sensors for detecting which side the line is on
- Frame-based lost detection is unreliable (sensor noise causes false triggers)
- Differential steering alone isn't smooth enough for tight curves

**Files:** `legacy/Pi.py` (382 lines), `legacy/advancedmovement.py` (512 lines)

---

### V2: PID + Mecanum Vector Drive (March 25-26, 2026)

**The problem:** V1 can't handle sharp curves, has no delivery zone detection, and recovery is unreliable.

**Major additions:**

1. **Mecanum inverse kinematics** — new ESP32 command `mv_vector:vx,vy,omega`:
   ```
   Front-Left  = vx + vy + omega
   Front-Right = vx - vy - omega
   Rear-Left   = vx - vy + omega
   Rear-Right  = vx + vy - omega
   ```
   This gives true omnidirectional control: forward + strafe + rotate simultaneously.

2. **PID controller for steering:**
   ```
   error = turn_var  (from weighted sensor fusion)
   P = Kp × error
   I = Ki × accumulated_error  (with anti-windup)
   D = Kd × (error - last_error)
   omega = P + I + D
   ```
   PID smooths out the steering response and eliminates oscillation.

3. **Strafe correction** — small lateral errors corrected with `vy` (sideways slide) instead of pure rotation. Idea: if the line drifts slightly left, strafe right rather than rotate.

4. **Pseudo-distance integration** — replaced frame counting with `speed × dt` accumulation. Better estimates of how far the robot has moved without encoders.

5. **Delivery zone detection** — when all 5 sensors stay ON for > 0.4 seconds, it's a delivery zone. Robot creeps forward at low speed and stops (parking sequence).

6. **Side pivot recovery** — new ESP32 command `mv_sidepivot:front,rear%,dir` pivots around the rear axle for more reliable re-centering.

**GUI improvements:** Added PID debug values, vector output display, delivery zone progress bar.

**Results:** Better curve handling, successful delivery parking. But PID + strafe was complex — the robot sometimes overshot on sharp turns because the strafe component fought with the rotation.

**Key learnings:**
- `mv_vector` is the right abstraction — all future movement goes through it
- PID works but is hard to tune for mecanum (4 independent wheels = complex dynamics)
- Strafe correction looks good in theory but confuses the robot on sharp curves
- Delivery zone time-thresholding is simple and reliable

**Files:** `legacy/advancedv2.py` (707 lines)

---

### V3: The Breakthrough — Simplify Everything (March 26, 2026)

**The insight:** PID + strafe is overengineered. The robot handles curves better when it just **slows down and rotates hard** — like a human turning a car by braking into the curve.

**What changed:**

1. **Removed PID entirely.** Replaced with simple proportional steering:
   ```
   omega = turn_var × OMEGA_GAIN × speed_multiplier
   ```
   That's it. No integral term, no derivative term, no anti-windup. Just proportional.

2. **Removed strafe correction.** `vy = 0` always during autonomous mode. Strafing is only for manual control.

3. **Curve slowdown system (the key innovation):**
   ```python
   turn_ratio = abs(turn_var) / MAX_TURN_STRENGTH   # 0.0 = straight, 1.0 = sharpest turn
   speed_scale = 1.0 - (1.0 - 0.20) × (turn_ratio ^ 1.5)
   forward_speed = base_speed × speed_scale
   ```

   | Turn severity | Forward speed | What happens |
   |:---:|:---:|---|
   | 0% (straight) | 100% | Full speed ahead |
   | 30% (gentle) | 84% | Barely slows |
   | 50% (moderate) | 60% | Noticeable braking |
   | 70% (sharp) | 41% | Significant slowdown |
   | 100% (hardest) | 20% | Crawling + maximum rotation |

   The exponent (1.5) means gentle curves stay fast while sharp curves get aggressive braking. This is the single biggest improvement across all versions.

4. **Sweep-turn recovery** — when the robot loses the line, instead of just coasting forward, it actively sweeps (rotates) in the last known turn direction while barely moving forward. This catches the line faster.

5. **Time-based lost detection** — requires 1.2 seconds of continuous no-line before declaring LOST (and only after having seen the line at least once). Eliminates false triggers at startup.

6. **Enhanced Pygame GUI (700×580):**
   - Two-column layout with sensor arc, turn bar, stats cards
   - Radar-style vector field with animated arrow and rotation arc
   - Throttle gauge, delivery zone progress bar
   - Color-coded state pills in header

**Results:** **First in class for line following.** The robot handles all curve types reliably. The combination of slowing down + rotating hard through curves is far more robust than the complex PID+strafe approach.

**Philosophy:** V3 proves that simpler is better. A proportional controller with good speed management beats a PID controller with bad speed management every time.

**Files:** `Minilab5/linefollower.py` (729 lines — the monolith)

---

### V4: Modular Architecture — Project Sonny (April 7, 2026)

**The problem:** V3 is a 729-line monolith. Adding vision, voice, and expression requires restructuring into modules.

**What V4 adds:**

The V3 line-following algorithm is preserved exactly as-is, but extracted into `alfred/navigation/line_follower.py`. Everything else is new:

| Subsystem | What it does |
|-----------|-------------|
| **Vision** | OpenCV camera, bird's-eye-view transform, ArUco marker detection with 6-DOF pose, contour obstacle detection, MediaPipe face/hand/gesture recognition, track mapping |
| **Navigation** | V3 line follower, pure pursuit path planner, ArUco approach controller, potential field obstacle avoidance, autonomous patrol |
| **Voice** | Whisper STT with "Hello Sonny" wake word, 8-intent keyword classifier, Piper/espeak TTS with 13 butler phrases |
| **Expression** | OLED animated eyes (8 emotions, gaze tracking, auto-blink), NeoPixel LED ring (10 states, pulse, rainbow), head servo (nod, shake, person tracking), personality engine |
| **FSM** | 17 states: IDLE, LISTENING, FOLLOWING, ENDPOINT, PARKING, ARUCO_SEARCH, ARUCO_APPROACH, BLOCKED, REROUTING, PATROL, PERSON_APPROACH, DANCING, PHOTO, LOST_REVERSE, LOST_PIVOT, STOPPING, SLEEPING |
| **GUI** | Enhanced Pygame dashboard with camera feed, voice status, 17-state display |

**Graceful degradation:** Every hardware import uses `try/except`. No camera? Skip vision. No mic? Skip voice. No OLED? Track state internally. Works on a dev laptop with zero hardware.

**17-State FSM:**
```
                         ┌──── "Hello Sonny" ────┐
                         ▼                        │
┌──────┐  wake word  ┌──────────┐  intent    ┌────────┐
│ IDLE │────────────►│ LISTENING │──────────►│ ACTION │
└──┬───┘             └──────────┘            └────────┘
   │                                              │
   │ voice: "follow"    ┌───────────────┐         │
   ├───────────────────►│   FOLLOWING   │◄────────┤
   │                    └───┬───┬───┬───┘         │
   │                        │   │   │              │
   │              ┌─────────┘   │   └──────────┐  │
   │              ▼             ▼               ▼  │
   │        ┌──────────┐ ┌──────────┐ ┌──────────┐│
   │        │ ENDPOINT │ │LOST_REV  │ │ BLOCKED  ││
   │        └────┬─────┘ └────┬─────┘ └────┬─────┘│
   │             ▼            ▼             ▼      │
   │        ┌──────────┐ ┌──────────┐ ┌──────────┐│
   │        │ PARKING  │ │LOST_PIVOT│ │REROUTING ││
   │        └──────────┘ └──────────┘ └──────────┘│
   │                                               │
   │ voice: "patrol"    ┌──────────┐               │
   ├───────────────────►│  PATROL  ├──► PERSON_APPROACH
   │                    └──────────┘               │
   │ voice: "dance"     ┌──────────┐               │
   ├───────────────────►│ DANCING  │◄──────────────┤
   │                    └──────────┘               │
   │ voice: "photo"     ┌──────────┐               │
   ├───────────────────►│  PHOTO   │◄──────────────┤
   │                    └──────────┘               │
   │ voice: "go to aruco" ┌────────────┐           │
   ├─────────────────────►│ARUCO_SEARCH│──►ARUCO_APPROACH
   │                      └────────────┘           │
   │ voice: "sleep"     ┌──────────┐               │
   └───────────────────►│ SLEEPING │◄──────────────┘
                        └──────────┘
```

---

## Line Following Algorithm (V3 — Core Algorithm)

The autonomous line follower uses a **6-state FSM** with proportional omega steering and curve slowdown:

### Steering

```python
# Weighted sensor fusion (W, NW, N, NE, E)
turn_strengths = [-7, -4.5, 0, +4.5, +7]
turn_var = weighted_average(active_sensors, turn_strengths)

# Turn ratio: 0.0 = straight, 1.0 = hardest turn
turn_ratio = abs(turn_var) / 9.0

# Forward speed drops on curves (power curve)
speed_scale = 1.0 - 0.80 × (turn_ratio ^ 1.5)
vx = internal_speed × multiplier × speed_scale

# Rotation: proportional to turn error
omega = turn_var × 4.5 × multiplier / 5.0

# Send to ESP32
mv_vector(vx, 0, omega)
```

### FSM States

| State | Trigger | Behaviour |
|-------|---------|-----------|
| **FOLLOWING** | Default | Proportional omega + curve slowdown |
| **ENDPOINT** | All 5 sensors ON | Slow crawl, detect delivery zone |
| **PARKING** | Delivery zone confirmed (>0.4s) | Creep forward, then stop |
| **LOST_REVERSE** | Line lost for 1.2s | Back up to last position |
| **LOST_PIVOT** | After reversing | Pivot in last turn direction |
| **STOPPED** | After parking or manual stop | Graceful deceleration |

---

## ESP32 Commands

| Command | Parameters | Action |
|---------|-----------|--------|
| `mv_vector` | vx, vy, omega | **Primary.** Mecanum IK: FL=vx+vy+omega, FR=vx-vy-omega, RL=vx-vy+omega, RR=vx+vy-omega |
| `mv_sidepivot` | front, rear%, dir | Pivot around rear axle for recovery |
| `mv_fwd` | speed | All wheels forward |
| `mv_rev` | speed | All wheels backward |
| `mv_left` / `mv_right` | speed | Mecanum strafe |
| `mv_turnleft` / `mv_turnright` | speed | Tank rotation |
| `mv_curve` | left, right | Differential per-side speed |
| `stop` | 0 | All motors stop |

Speed values: 0-100%, mapped internally to PWM 50-200.

---

## Tuning Guide

All parameters live in `alfred/config.py` (V4) or at the top of `Minilab5/linefollower.py` (V3).

### Key Parameters

| Parameter | Default | Increase if... | Decrease if... |
|-----------|:-------:|----------------|----------------|
| `OMEGA_GAIN` | 4.5 | Slow to react to curves | Oscillates/overshoots |
| `CURVE_SLOW_FACTOR` | 0.20 | Stalls on tight curves | Too fast through curves |
| `CURVE_SLOW_EXPO` | 1.5 | Speed drops too early | Speed drops too late |
| `DEFAULT_SPEED` | 35 | Too slow overall | Too fast to control |

### Presets

| Profile | Speed | Omega | Slow Factor | Use Case |
|---------|:-----:|:-----:|:-----------:|----------|
| Conservative | 25 | 3.0 | 0.15 | Carrying fragile payload |
| Balanced | 35 | 4.5 | 0.20 | General purpose |
| Aggressive | 50 | 6.0 | 0.30 | Speed competition |

---

## Debug GUI

The Pygame dashboard (900×620) provides real-time monitoring:

| Panel | Description |
|-------|-------------|
| **Sensor Arc** | 5 IR sensors with glow effects |
| **Turn Bar** | Color-coded turn indicator (green/yellow/red) |
| **Stats Cards** | Speed, algorithm speed, pseudo-distance |
| **Vector Field** | Radar-style vx/vy arrow + rotation arc |
| **Throttle Gauge** | Color-coded speed bar |
| **Camera Feed** | Live camera preview (when available) |
| **Voice Status** | MIC ON/OFF indicator |
| **FSM State** | 17-state pill with colour coding |

### Controls

| Key | Action |
|-----|--------|
| **W/S** | Forward / Reverse |
| **A/D** | Strafe left / right |
| **Q/E** | Rotate left / right |
| **M** | Toggle auto / manual mode |
| **F** | Quick-start line following |
| **1/2** | Decrease / increase speed |
| **Space** | Emergency stop |
| **Esc** | Quit |

All keys are combinable for omnidirectional manual control.

---

## Voice Commands

Say **"Hello Sonny"** followed by:

| Command | What Sonny does |
|---------|----------------|
| "follow the track" | Start line following |
| "go to aruco marker" | Search and approach ArUco |
| "dance" | 5-second dance routine |
| "take a photo" | Capture and save image |
| "come here" | Approach detected person |
| "patrol" | Autonomous wander |
| "stop" | Immediate stop |
| "sleep" | Enter sleep mode |

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

Built for HKU School of Innovation. ESP32-S3 + Raspberry Pi 5 + Mecanum drive.
