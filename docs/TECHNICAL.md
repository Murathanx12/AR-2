# Sonny V4 -- Technical Reference

This document explains how the Sonny robot works internally. It is written for a teammate joining the project and wanting to understand the code, data flow, and design decisions.

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [UART Protocol](#uart-protocol)
3. [Finite State Machine](#finite-state-machine)
4. [Vision Pipeline](#vision-pipeline)
5. [Voice Pipeline](#voice-pipeline)
6. [Navigation](#navigation)
7. [Expression System](#expression-system)
8. [GUI Dashboard](#gui-dashboard)
9. [Phone App / Web Relay](#phone-app--web-relay)
10. [Pin Assignments](#pin-assignments)

---

## System Architecture

Sonny has two processors that divide the work:

```
┌─────────────────────────────────────────────────────────┐
│                    Raspberry Pi 5                        │
│                                                         │
│  ┌─────────┐  ┌────────┐  ┌─────────┐  ┌────────────┐  │
│  │  Voice   │  │ Vision │  │   FSM   │  │ Expression │  │
│  │ Listener │  │ Camera │  │ 30 Hz   │  │  Eyes/LED  │  │
│  │ (VOSK)   │  │ ArUco  │  │ 17-state│  │  Head/TTS  │  │
│  │ Intent   │  │ Face   │  │ dispatch│  │ Personality│  │
│  │ Speaker  │  │ Hand   │  │         │  │  10 Hz     │  │
│  │ Claude   │  │ Obst.  │  │         │  │            │  │
│  └────┬─────┘  └───┬────┘  └────┬────┘  └────────────┘  │
│       │            │            │                        │
│       └────────────┴────────┬───┘                        │
│                             │                            │
│                    ┌────────┴────────┐                   │
│                    │   UART Bridge   │                   │
│                    │  /dev/ttyAMA2   │                   │
│                    │  115200 baud    │                   │
│                    └────────┬────────┘                   │
└─────────────────────────────┼───────────────────────────┘
                              │  TX: mv_vector:vx,vy,omega\n
                              │  RX: IR_STATUS:XX\n
                              │  RX: DIST:XX.X\n
┌─────────────────────────────┼───────────────────────────┐
│                    ESP32-S3 │                            │
│                    ┌────────┴────────┐                   │
│                    │  UART Parser    │                   │
│                    └───┬───┬───┬─────┘                   │
│                        │   │   │                         │
│  ┌─────────────┐  ┌────┴┐ ┌┴───┴──┐  ┌──────────────┐   │
│  │ Motor PWM   │  │ IR  │ │Ultra- │  │ NeoPixel LED │   │
│  │ 4x Mecanum  │  │ 5x  │ │sonic  │  │ + Buzzer     │   │
│  │ FL/FR/RL/RR │  │ 20Hz│ │10Hz   │  │              │   │
│  └─────────────┘  └─────┘ └───────┘  └──────────────┘   │
└─────────────────────────────────────────────────────────┘
```

**Data flow in one tick (33 ms at 30 Hz):**

1. The Pi reads a camera frame and shares it across all vision subsystems.
2. The FSM controller dispatches the handler for the current state.
3. The state handler reads sensor data (IR bits, ultrasonic distance) from the UART bridge.
4. Based on the state logic, it computes a movement command `(vx, vy, omega)`.
5. The command is sent to the ESP32 over UART.
6. The personality engine updates eyes, LEDs, and head servo at 10 Hz.
7. The GUI renders everything to the screen at 30 Hz.

**Graceful degradation:** Every subsystem is wrapped in a try/except during init. If the camera is not plugged in, vision is skipped. If VOSK is not installed, voice is skipped. The robot still runs with whatever hardware is available.

---

## UART Protocol

All messages are newline-terminated ASCII strings.

### Pi to ESP32 (commands)

| Command | Format | Example |
|---------|--------|---------|
| Vector movement | `mv_vector:vx,vy,omega\n` | `mv_vector:30,0,15\n` |
| Forward | `mv_fwd:speed\n` | `mv_fwd:50\n` |
| Reverse | `mv_rev:speed\n` | `mv_rev:30\n` |
| Strafe left | `mv_left:speed\n` | `mv_left:40\n` |
| Strafe right | `mv_right:speed\n` | `mv_right:40\n` |
| Turn left | `mv_turnleft:speed\n` | `mv_turnleft:30\n` |
| Turn right | `mv_turnright:speed\n` | `mv_turnright:30\n` |
| Spin left | `mv_spinleft:speed\n` | `mv_spinleft:60\n` |
| Spin right | `mv_spinright:speed\n` | `mv_spinright:60\n` |
| Side pivot | `mv_sidepivot:front,rear%,dir\n` | `mv_sidepivot:80,15,1\n` |
| Curve | `mv_curve:left,right\n` | `mv_curve:40,60\n` |
| Stop | `stop:0\n` | `stop:0\n` |
| LED colour | `led:r,g,b\n` | `led:0,255,0\n` |
| LED pattern | `led_pattern:id\n` | `led_pattern:2\n` |
| Buzzer | `buzzer:freq,duration_ms\n` | `buzzer:1000,200\n` |

LED pattern IDs: 0 = solid, 1 = pulse, 2 = rainbow, 3 = blink, 4 = breathe.

Speed values range from 0-150. The ESP32 maps these to PWM duty cycles (50-200).

### ESP32 to Pi (sensor data)

| Message | Format | Rate | Example |
|---------|--------|------|---------|
| IR sensors | `IR_STATUS:XX\n` | 20 Hz | `IR_STATUS:14\n` (binary 01110) |
| Ultrasonic | `DIST:XX.X\n` | 10 Hz | `DIST:23.5\n` |

The IR status is a 5-bit integer where each bit represents one sensor (W, NW, N, NE, E). A bit value of 1 means the sensor sees the line.

The ultrasonic distance is in centimetres. A value of -1 means no reading (sensor not connected or no echo received).

The `UARTBridge` class (`alfred/comms/uart.py`) handles all serial I/O in a background thread. It exposes `get_ir_bits()` and `get_distance()` methods that return the latest sensor values without blocking.

---

## Finite State Machine

The FSM has **17 states** defined as an IntEnum in `alfred/fsm/states.py`. The main loop in `AlfredFSM.run()` calls `tick()` at 30 Hz. Each tick dispatches to a state-specific handler via a dict lookup.

### State Diagram

```
                    ┌──────────────────┐
                    │      IDLE        │ <──── "stop" from any state
                    │  (wait for wake) │
                    └────────┬─────────┘
                             │ wake word detected
                             v
                    ┌────────────────────┐
                    │    LISTENING       │ <──── commands arrive via callback
                    │  (wait for cmd)    │
                    └──┬──┬──┬──┬──┬──┬─┘
                       │  │  │  │  │  │
          ┌────────────┘  │  │  │  │  └──────────────┐
          v               v  │  v  v                  v
     ┌──────────┐  ┌────────┐│┌──────┐ ┌──────────┐ ┌────────┐
     │FOLLOWING  │  │ARUCO   ││PATROL │ │ DANCING  │ │ PHOTO  │
     │(line fol.)│  │SEARCH  ││       │ │          │ │        │
     └──┬──┬──┬─┘  └───┬────┘│└──┬───┘ └──────────┘ └────────┘
        │  │  │        │     │   │
        v  │  v        v     │   v
  ┌──────┐│┌──────┐┌───────┐ │ ┌──────────────┐
  │ENDPT ││LOST   ││ARUCO  │ │ │PERSON        │
  │      ││REVERSE││APPR.  │ │ │APPROACH      │
  └──┬───┘│└──┬───┘└───────┘ │ └──────────────┘
     v    │   v              │
  ┌──────┐│┌──────┐          │
  │PARK  ││LOST   │          │
  │      ││PIVOT  │          │
  └──────┘│└──────┘          │
          │                  │
          v                  v
     ┌──────────┐     ┌──────────┐
     │ BLOCKED  │     │ SLEEPING │
     │(obstacle)│     │(wake req)│
     └──┬───────┘     └──────────┘
        │
        v
     ┌──────────┐
     │REROUTING │
     └──────────┘
```

### All 17 States

| # | State | Description | Transitions to |
|---|-------|-------------|----------------|
| 0 | IDLE | Waiting for wake word | LISTENING (on wake) |
| 1 | LISTENING | Awake, waiting for voice command | Any command state |
| 2 | FOLLOWING | Line following using IR sensors | ENDPOINT, LOST_REVERSE, BLOCKED |
| 3 | ENDPOINT | All 5 IR sensors active (crossroad/junction) | PARKING, FOLLOWING, LOST_REVERSE |
| 4 | PARKING | Driving forward into delivery zone | IDLE (when parked) |
| 5 | ARUCO_SEARCH | Rotating slowly, scanning for ArUco markers | ARUCO_APPROACH, BLOCKED |
| 6 | ARUCO_APPROACH | Driving toward detected marker | IDLE (arrived), ARUCO_SEARCH (lost), BLOCKED |
| 7 | BLOCKED | Obstacle detected, stopped, waiting for clearance | Resume previous state |
| 8 | REROUTING | Computing avoidance manoeuvre | FOLLOWING |
| 9 | PATROL | Autonomous wander with person/gesture detection | PERSON_APPROACH, FOLLOWING, PHOTO, IDLE |
| 10 | PERSON_APPROACH | Driving toward a detected face | IDLE (reached), PATROL (lost) |
| 11 | DANCING | Timed dance routine (5 s) with rainbow LEDs | IDLE |
| 12 | PHOTO | Capture a photo from camera | IDLE |
| 13 | LOST_REVERSE | Lost the line, reversing to re-find it | LOST_PIVOT, FOLLOWING |
| 14 | LOST_PIVOT | Lost the line, pivoting in place to re-find it | FOLLOWING |
| 15 | STOPPING | Transitional stop state | IDLE |
| 16 | SLEEPING | Deep sleep, LEDs off, requires wake word | LISTENING |

### State Transition Rules

- **"stop"** always works from any state -- it immediately transitions to IDLE.
- **Obstacle detection (R4):** During FOLLOWING, ARUCO_SEARCH, ARUCO_APPROACH, and PATROL, the ultrasonic sensor is checked every tick. If distance < 20 cm, transition to BLOCKED.
- **BLOCKED recovery:** When the obstacle clears, the FSM resumes whatever state it was in before (stored in `_previous_state`).
- **Line follower sub-FSM:** The FOLLOWING state delegates to the `LineFollower` class which has its own internal 6-state machine. The main FSM mirrors those sub-states (ENDPOINT, PARKING, LOST_REVERSE, LOST_PIVOT).

### R5 Indicators

Every state transition triggers:
1. **LED colour change** via UART (`led:r,g,b\n` + `led_pattern:id\n`)
2. **TTS announcement** via espeak-ng (e.g., "Following the track.", "Obstacle detected.")
3. **Buzzer** on specific events (arrival beep, shutter sound)
4. **Eye emotion change** via the personality engine

The full LED colour map is defined in `STATE_LED_COLORS` in `controller.py`.

---

## Vision Pipeline

All vision processing happens on the Pi using OpenCV and MediaPipe.

```
USB Camera
    │
    v
CameraManager.read_frame()     # returns BGR numpy array (800x600 @ 30fps)
    │
    ├──> ArucoDetector.detect()         # DICT_4X4_50, returns id + corners + center + size
    │         └──> estimate_pose()      # optional, needs camera calibration
    │
    ├──> ObstacleDetector.detect()      # contour-based, returns bounding boxes
    │         └──> is_path_clear()      # checks centre region of frame
    │
    ├──> PersonDetector.detect_faces()  # MediaPipe face detection, returns bbox + center + confidence
    │         └──> detect_hands()       # MediaPipe hand landmarks
    │               └──> get_gesture()  # classifies into 6 gestures
    │
    └──> BirdEyeView.transform()       # perspective warp (for course mapping)
```

### ArUco Detection (R3)

- Uses OpenCV's `cv2.aruco` module with `DICT_4X4_50` dictionary.
- Returns a list of detected markers, each containing: `id`, `corners` (4 corner points), `center` (cx, cy), and `size` (average side length in pixels).
- Pose estimation is available when the camera is calibrated, but the approach algorithm works without it (visual-only mode).

### Gesture Recognition (EC1)

Six recognised gestures, detected via MediaPipe hand landmarks:

| Gesture | Description | Action in PATROL |
|---------|-------------|------------------|
| fist | Closed hand | (no action) |
| open | Open palm | Stop, go to IDLE |
| thumbs_up | Thumb extended | Approach person |
| peace | Index + middle extended | Take photo |
| point | Index finger extended | Start line following |
| wave | Open hand waving | (no action) |

### Camera-Based Obstacle Detection (currently disabled)

The contour-based obstacle detector had too many false positives from shadows and dark floor patches. Only the HC-SR04 ultrasonic sensor is used for obstacle detection (R4). The camera detector code is still in the codebase but not triggered by the FSM.

---

## Voice Pipeline

```
USB Microphone
    │
    v
PyAudio (16 kHz, mono, 4000-sample chunks)
    │
    │  [muted while speaker is active -- prevents echo loop]
    v
VOSK KaldiRecognizer (grammar-constrained)
    │
    │  Grammar limits recognized words to ~55 command vocabulary words
    │  This prevents VOSK from hearing random sentences from background noise
    v
VoiceListener._process(text)
    │
    ├──> Wake word check ("hello sonny" and variants)
    │    Wake once, stay awake -- no need to repeat
    │
    ├──> "stop" / "halt" / "freeze" -- always handled, even before wake
    │
    └──> (if awake) pass text to FSM callback
              │
              v
         IntentClassifier.classify(text)
              │
              │  Exact substring match against keyword lists
              │  Longest keyword matched first per intent
              │  Returns (intent_name, 1.0) or ("unknown", 0.0)
              v
         AlfredFSM._on_voice_command()
              │
              ├──> Map intent to FSM state transition
              ├──> TTS confirmation via Speaker
              └──> "chat" intent --> ConversationEngine (Claude API)
```

### Wake Word Design

The wake phrase is "Hello Sonny". The listener also accepts common misheard variants: "hello sunny", "hello sony", "hey sonny", "hi sonny", and bare "hello".

Once the wake word is detected, the robot stays awake. All subsequent speech is treated as commands. Saying "sleep" puts it back to sleep, requiring the wake word again.

### Grammar-Constrained Recognition

VOSK is configured with a JSON grammar list of approximately 55 allowed words. This means VOSK will only ever output combinations of these words, dramatically reducing false positives from background noise or music. The tradeoff is that anything outside the grammar is silently ignored.

### Echo Prevention

When the robot speaks via TTS, the microphone picks up the speaker output and could trigger false commands. To prevent this, the `VoiceListener` checks the `Speaker.is_speaking` property every audio chunk. While speaking, audio is discarded. A 1-second cooldown (`_muted_until`) is added after speech ends to account for reverb.

### TTS Engine

The Speaker class tries engines in order:
1. **piper-tts** -- neural TTS, natural sounding, requires ONNX model file
2. **espeak-ng** with mbrola voice (mb-us1) -- robotic but reliable
3. **espeak-ng** default voice -- fallback
4. **Log only** -- if no TTS engine is found

TTS runs in a background thread to avoid blocking the FSM loop.

### Claude API Conversation (EC3)

The `ConversationEngine` sends user text to `claude-haiku-4-5` with a butler personality system prompt. Responses are limited to 100 tokens (1-2 sentences) because they are spoken aloud. Conversation history is kept to the last 6 messages. Falls back to canned responses if the API key is missing or the network is down.

---

## Navigation

### Line Follower (R2)

**File:** `alfred/navigation/line_follower.py`

The line follower has its own internal 6-state FSM:

```
FOLLOWING <--> ENDPOINT --> PARKING --> (finished)
    |                        ^
    v                        |
LOST_REVERSE --> LOST_PIVOT -+
                             |
                          STOPPED
```

**Weighted sensor algorithm:**

The 5 IR sensors are positioned left-to-right: W, NW, N, NE, E. Each has a turn strength:

```
W = -7.0,  NW = -4.5,  N = 0.0,  NE = +4.5,  E = +7.0
```

When sensors detect the line, the weighted average of active sensor turn strengths gives the `turn_var`. This drives omega (rotation). Each sensor also has a move strength:

```
W = 3.8,  NW = 4.2,  N = 5.0,  NE = 4.2,  E = 3.8
```

The weighted average of active sensor move strengths gives the target forward speed. This means the robot goes fastest when the centre sensor is active (straight line) and slows down on curves.

**Curve handling:**

When `turn_var` is large (sharp curve), the forward speed is reduced:

```python
speed_scale = 1.0 - (1.0 - curve_slow_factor) * (turn_ratio ** curve_slow_expo)
```

With `curve_slow_factor = 0.20` and `curve_slow_expo = 1.5`, the robot keeps 80% speed on gentle curves but drops to 20% on the sharpest turns.

**Lost-line recovery:**

1. If no sensor sees the line for more than 1.2 seconds, the robot sweeps (turns in the direction of the last known turn) while creeping forward slowly.
2. If still lost, it enters LOST_REVERSE: backs up a short distance.
3. Then LOST_PIVOT: pivots in place in the direction of the last known turn.
4. If any sensor finds the line again, it returns to FOLLOWING.

**Endpoint detection:**

When all 5 sensors are active simultaneously (a crossroad or wide line), the follower transitions to ENDPOINT. If all sensors stay active for 0.4 seconds, it transitions to PARKING (drives forward a short distance, then stops and signals delivery complete).

### ArUco Approach (R3)

**File:** `alfred/navigation/aruco_approach.py`

Two modes:

**Visual-only mode (primary, no camera calibration needed):**

1. Marker centre pixel position and apparent size are read from the detector.
2. An exponential moving average (EMA, alpha = 0.4) smooths both the centre-x and size values across frames. This reduces jitter from frame-to-frame noise.
3. Steering: proportional to the horizontal offset of the marker from the image centre. `omega = turn_speed * (cx - frame_centre) / (frame_width / 2)`.
4. Forward speed: proportional to distance estimate (smaller marker = faster approach), reduced when steering hard to prevent overshooting.
5. When the marker pixel size exceeds `stop_size` (150 pixels), the robot has arrived.
6. Below 80% of stop_size, the robot creeps at max 18 speed for precise stopping.

**Calibrated mode (when camera matrix is available):**

Uses OpenCV `solvePnP` pose estimation to get the 3D translation vector (tx, ty, tz) in metres. Forward speed and lateral strafe are proportional to tz and tx respectively. Arrival when distance < 0.05 m.

Both modes drive steering and forward speed simultaneously (not the common "centre first, then drive forward" approach), resulting in smooth curved approaches.

### Obstacle Avoidance (R4)

The primary obstacle sensor is the HC-SR04 ultrasonic. It reports distance at 10 Hz via UART. If distance < 20 cm, the FSM transitions to BLOCKED (motors stop immediately).

The BLOCKED state waits until the ultrasonic reading clears, then resumes the previous state. Camera-based obstacle detection is implemented but disabled due to false positive issues.

---

## Expression System

The expression system makes the robot feel alive. It coordinates four subsystems through the `PersonalityEngine`.

### OLED Eyes

**File:** `alfred/expression/eyes.py`

Renders animated eyes to a 128x64 pixel SSD1306 OLED display (and to the GUI simultaneously). Features:

**8 emotions**, each with different eye shape parameters:

| Emotion | Width | Height | Shape | When used |
|---------|-------|--------|-------|-----------|
| neutral | 28 | 28 | Round | IDLE, FOLLOWING |
| happy | 30 | 20 | Wide, squinted | PARKING, PATROL, PERSON_APPROACH |
| sad | 24 | 30 | Tall, droopy | (available, not currently mapped) |
| angry | 32 | 18 | Flat, narrow | BLOCKED |
| surprised | 34 | 34 | Large, round | LISTENING, ENDPOINT |
| sleepy | 28 | 10 | Thin slits | SLEEPING |
| love | 30 | 28 | Round + hearts | DANCING |
| confused | 26 | 26 | Medium + raised brow | ARUCO_SEARCH, LOST states |

**Gaze tracking:** When a face is detected by the person detector, the eyes look toward it. The gaze position maps the face's pixel coordinates in the camera frame to a (0-1, 0-1) range. The eye pupils shift by up to 12 pixels horizontally and 6 pixels vertically.

**Auto-blink:** Every 4 seconds, the eyes automatically blink (0.15 s close + 0.15 s open). The blink squashes the eye height by 90%.

### NeoPixel LEDs

4x WS2812B LEDs controlled via UART commands to the ESP32. Each FSM state has a colour:

- IDLE: dim blue (0, 0, 100)
- FOLLOWING: green (0, 255, 0)
- BLOCKED: red (255, 0, 0) with blink pattern
- DANCING: white (255, 255, 255) with rainbow pattern
- SLEEPING: off with dim blue breathe pattern
- (and so on for all 17 states)

### Head Servo

A PCA9685-controlled servo on channel 0 tilts the robot's "head" (the monitor mount). Range is 45 to 135 degrees, centre at 90. During PATROL and PERSON_APPROACH, the head tracks detected faces. Otherwise it centres.

### Personality Engine

**File:** `alfred/expression/personality.py`

Maps each FSM state name to an expression configuration (emotion + LED state + head behaviour). Updates at 10 Hz to avoid overwhelming the I2C bus (the OLED and PCA9685 share I2C).

Only triggers full expression updates on state transitions. Between transitions, it only updates gaze tracking and auto-blink.

---

## GUI Dashboard

**File:** `alfred/gui/debug_gui.py`

A 1280x720 Pygame window that shows all robot subsystems at a glance. Designed for the 14" USB-C monitor mounted on the robot.

```
┌──────────────────────────────────────────────────────────┐
│  HEADER: "SONNY" + state name + mode pill + mic/lang     │
├──────────────────────────────┬───────────────────────────┤
│                              │  EYES panel               │
│                              │  (OLED render or fallback) │
│  CAMERA FEED                 ├───────────────────────────┤
│  (with ArUco / face /        │  IR SENSORS panel         │
│   obstacle overlays)         │  [W] [NW] [N] [NE] [E]   │
│                              │  + ultrasonic distance    │
│                              ├───────────────────────────┤
│                              │  MOVEMENT panel           │
│  Detection counts overlay    │  Vector viz + vx/vy/omega │
├──────────────────────────────┴───────────────────────────┤
│  VOICE INPUT  │  OUTPUT / GESTURE  │  EVENT LOG          │
│  "heard text" │  "said text"       │  timestamped events │
│  intent match │  gesture name      │  scrolling          │
└──────────────────────────────────────────────────────────┘
```

**Camera panel** (left, 55% width): Shows the live camera feed with coloured overlays for detected ArUco markers (green polylines + ID + size), face bounding boxes (green rectangles), and obstacle bounding boxes (red rectangles). A detection summary bar at the bottom shows counts.

**Eyes panel** (top right): Renders the OLED eye frame scaled up and tinted with the current state colour. Falls back to simple drawn ellipses if the eye controller is not available.

**IR Sensors panel** (middle right): Shows 5 rectangles for W/NW/N/NE/E sensors, green when active, dark when inactive. Also shows ultrasonic distance (red if < 20 cm).

**Movement panel** (bottom right): A circular vector visualization showing the current movement direction as an arrow. Numeric readout of vx, vy, and omega values.

**Bottom row** (3 columns): Voice input (what was heard + intent classification), voice output and gesture recognition, and a scrolling event log with timestamps.

---

## Phone App / Web Relay

**Directory:** `alfred/web/`

An experimental web-based relay that allows controlling the robot from a phone browser. This was explored as a workaround for the weak USB microphone -- the phone's microphone captures speech, sends it to the Pi over WiFi, and the Pi processes it as if it came from the USB mic.

This module is not yet integrated into the main FSM loop.

---

## Pin Assignments

Full wiring details are in `docs/WIRING.md`. Summary:

### ESP32-S3 GPIO

| Pin | Function |
|-----|----------|
| GPIO4 | HC-SR04 ultrasonic trigger |
| GPIO2 | HC-SR04 ultrasonic echo |
| GPIO5 | IR sensor W (far left) |
| GPIO6 | IR sensor NW |
| GPIO7 | IR sensor N (centre) |
| GPIO15 | IR sensor NE |
| GPIO45 | IR sensor E (far right) |
| GPIO48 | WS2812B NeoPixel data (4 LEDs) |
| GPIO46 | Piezo buzzer |
| TX/RX | UART to Pi (115200 baud) |
| Motor pins | Defined in ESP32 firmware (`esp32/src/main.cpp`) |

### Raspberry Pi 5

| Interface | Function |
|-----------|----------|
| /dev/ttyAMA2 | UART to ESP32 (TX, RX, GND) |
| I2C bus 1 | SSD1306 OLED (0x3C), PCA9685 servo controller (0x40) |
| USB port 1 | Camera |
| USB port 2 | Microphone |
| USB port 3 | Speaker |
| USB port 4 | WiFi adapter (RTL8811AU) |
| Micro-HDMI | 14" monitor |

### PCA9685 Servo Channels

| Channel | Function |
|---------|----------|
| 0 | Head tilt servo (45-135 deg, centre 90) |
| 1-4 | Robot arm servos (SG90) |
