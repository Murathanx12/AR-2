# TODO — Demo Day Prep (April 24, 2026)

Last updated: April 23, 2026

## BUGS FOUND IN CODE (fix today)

### BUG 1: Phone mic does NOT wake the robot (CRITICAL)
**File:** `alfred/web/app.py:506-515`
**Problem:** The `/audio` endpoint calls `fsm._on_voice_command(text)` FIRST, then
checks wake state AFTER. But `_on_voice_command` drops everything if not awake
(it calls `self._process(text)` in the listener, but the web path bypasses the
listener entirely). The wake check at line 509 calls `_do_wake()` but this only
sets the internal flag — the command that came WITH the wake phrase is lost.
**Impact:** "Hello Sonny, follow the track" from the phone mic will wake but NOT
execute "follow the track". User has to say wake phrase, then say command separately.
**Fix:** Check wake state BEFORE dispatching command. If not awake, check for wake
phrase first, wake up, then dispatch the command-after-wake.

### BUG 2: Phone mic classifies intent AFTER dispatching command
**File:** `alfred/web/app.py:518-520`
**Problem:** `classify()` is called after `_on_voice_command()` just to populate the
JSON response. But `_on_voice_command()` calls `classify()` internally too — so intent
classification runs TWICE per phone mic input. Wasted API call ($0.0003 each, adds up).
**Fix:** Return the intent/confidence from the FSM dispatch instead of re-classifying.

### BUG 3: Web video feed runs ArUco detection a SECOND time
**File:** `alfred/web/app.py:605-607`
**Problem:** The `/video_feed` endpoint calls `self.fsm.aruco_detector.detect(display)`
on EVERY frame to draw markers. But the FSM already detects once per tick and caches
results in `self._last_markers`. This is ~40ms wasted per frame at 1080p.
**Fix:** Use `self.fsm._last_markers` and call `draw_markers()` with cached results.

### BUG 4: ArUco approach returns None = "arrived" even when marker is just big
**File:** `alfred/navigation/aruco_approach.py:137-140`
**Problem:** `compute_visual_approach()` returns `None` (meaning "arrived") when
`dist_m <= STOP_DIST_M`. But the caller in controller.py:1018 treats `None` as
"call `_on_aruco_arrived()`" which stops motors and transitions to IDLE. This is
correct... BUT: `_on_aruco_arrived()` does NOT enter hold mode. Once in IDLE, if
the marker moves, the robot does nothing. The hold-mode logic (back up if too close,
nudge forward if drifted) is in `ArucoApproach` but never gets called after arrival.
**Impact:** Robot stops at marker but doesn't maintain 20cm distance. If marker
moves closer, robot doesn't back up. If marker moves away, robot doesn't follow.
**Fix:** Instead of transitioning to IDLE on arrival, stay in ARUCO_APPROACH and
let the hold-mode logic in `compute_visual_approach()` keep running. Only go to
IDLE on voice command or timeout.

### BUG 5: Google STT uses wrong sample rate
**File:** `alfred/voice/listener.py:256`
**Problem:** `sr.AudioData(audio_data, self.SAMPLE_RATE, 2)` hardcodes 16000 Hz
but `self._actual_rate` may be 44100 Hz (common for PCM2902 USB mics). The WAV
header tells Google "this is 16kHz" but the audio is actually 44.1kHz, making
everything sound like chipmunks. Google returns garbage or empty.
**Fix:** Use `self._actual_rate` instead of `self.SAMPLE_RATE`.

### BUG 6: NeoPixel LED commands sent over UART every state change (wasteful)
**File:** `alfred/fsm/controller.py:423-439`
**Problem:** `_update_led()` sends `cmd_led()` and `cmd_led_pattern()` commands
over UART on every state transition. LEDs are not installed. Each send takes
~1ms on UART, and the pattern commands confuse the ESP32 (it tries to parse them
but falls through to "Unknown command").
**Fix:** Remove all UART LED sends from FSM. Keep STATE_LED_COLORS dict for GUI.

### BUG 7: `_tick_blocked` only clears on ultrasonic — camera-only mode gets stuck
**File:** `alfred/fsm/controller.py:1049`
**Problem:** When running `--no-ultrasonic`, `_check_ultrasonic_obstacle()` always
returns False. So `_tick_blocked` checks `ultrasonic_clear` which is always True,
and immediately transitions back — creating a BLOCKED->APPROACH->BLOCKED flicker
if the camera obstacle check triggers entry. OR: if only ultrasonic triggered BLOCKED,
the robot exits immediately. There's no timeout or camera-based clear check.
**Fix:** Add camera clear check: path is clear when BOTH ultrasonic is clear AND
camera doesn't see a close obstacle. Add a minimum blocked duration (1s).

### BUG 8: Stale comment says ECHO_R_PIN 39 shared with NeoPixel
**File:** `esp32/src/main.cpp:42`
**Problem:** Comment says "shared with NeoPixel!" but NeoPixel was on GPIO48 and is
now removed entirely. Not a functional bug, but confusing.

---

## HOW ARUCO DISTANCE CALCULATION WORKS (and why it's not working)

### The Pinhole Model (aruco_approach.py:58-62)
```
distance_m = (PHYSICAL_MARKER_M * focal_px) / pixel_size
```
Where:
- `PHYSICAL_MARKER_M = 0.05` (5cm printed marker)
- `focal_px = FOCAL_RATIO * frame_width = 0.8 * 1920 = 1536 pixels`
- `pixel_size` = average side length of detected marker in pixels

**Example:** If marker appears 76.8 pixels wide on screen:
```
distance = (0.05 * 1536) / 76.8 = 1.0 meter
```

### Why it should stop at 20cm
At 20cm distance, the marker would appear:
```
pixel_size = (0.05 * 1536) / 0.20 = 384 pixels wide
```
That's 20% of the 1920px frame — very visible and reliable.

### The Hold-Distance Behavior (what SHOULD happen)
```
STOP_DIST_M  = 0.20  →  stop here (20cm)
HOLD_NEAR_M  = 0.15  →  closer than this → back up at speed -15
HOLD_FAR_M   = 0.30  →  farther than this → nudge forward at speed 10
APPROACH_REENGAGE_M = 0.35  →  marker moved far → full re-approach
```

### Why it's NOT working (BUG 4 above)
The FSM calls `_on_aruco_arrived()` which sends `cmd_stop()` and transitions
to IDLE. Once in IDLE, the hold-mode code in `compute_visual_approach()` never
runs again. The robot stops but doesn't maintain distance.

### The fix
Stay in ARUCO_APPROACH after hold-mode engages. Only announce arrival once.
The hold logic already handles backing up and re-approaching — it just needs
the FSM to keep ticking ARUCO_APPROACH instead of jumping to IDLE.

### Calibration (if distance is consistently wrong)
- Measure a known distance (e.g., hold marker exactly 50cm away)
- Read the `dist=X.XXm` from the log
- If off: `FOCAL_RATIO = measured_pixel_size * known_distance / (PHYSICAL_MARKER_M * frame_width)`
- If your printed marker isn't 5cm, change `PHYSICAL_MARKER_M`

---

## HARDWARE CHECKLIST (morning of April 24)

### Motors (BLOCKS EVERYTHING)
- [ ] Charge 12V battery overnight — check with multimeter (must be >10V)
- [ ] Run `python3 scripts/test_esp32.py` — does it show "UART connected"?
- [ ] Send `mv_fwd:50` manually — do wheels spin?
- [ ] If no: check GND wire between Pi and ESP32
- [ ] If no: try powering ESP32 from USB while 12V powers motor driver
- [ ] If yes but weak: battery is dying, swap/charge

### Ultrasonic Sensors (R4)
**Current status:** 3x HC-SR04 through logic level shifter — unreliable.

**Option A: Resistor divider (RECOMMENDED — 10 min fix)**
For EACH echo pin: 1kOhm from HC-SR04 ECHO to ESP32 GPIO, 2kOhm from GPIO to GND.
```
HC-SR04 ECHO (5V) ---[1kOhm]---+--- ESP32 GPIO (reads 3.3V)
                                |
                              [2kOhm]
                                |
                               GND
```
Trigger pins need NO conversion (3.3V drives HC-SR04 trigger fine).

**Option B: Center sensor only (5 min)**
Only wire up center sensor (GPIO18 trig, GPIO1 echo). L/R sensors disabled.
Run with `--no-ultrasonic` flag — camera-based obstacle detection handles the rest.

**Option C: Camera only (0 min — just use the flag)**
```
python3 Minilab5/alfred.py --demo --no-ultrasonic --enable-yolo
```
YOLO detects obstacles from camera. Slower but works without any wiring.

**Pin wiring reference (ESP32-S3):**
| Sensor | Trigger | Echo | Notes |
|--------|---------|------|-------|
| Left   | GPIO19  | GPIO20 | Needs voltage divider on echo |
| Center | GPIO18  | GPIO1  | Needs voltage divider on echo |
| Right  | GPIO40  | GPIO39 | Needs voltage divider on echo |

### Camera
- [ ] Plugged directly into Pi USB port (NOT through hub)
- [ ] Check with: `ls /dev/video*` — should show video0 or video1
- [ ] If config.py has `camera_index: 1` but only video0 exists, change to 0

### Audio
- [ ] USB speaker plugged directly into Pi (not through hub)
- [ ] Test TTS: `espeak-ng "Hello I am Sonny"` on Pi terminal
- [ ] USB mic plugged in (secondary — phone is primary for demo)
- [ ] Phone hotspot ready as backup Wi-Fi

---

## WIRING DIAGRAM (quick reference)

### Pi 5 to ESP32-S3 (UART)
```
Pi GPIO4  (pin 7)  ---> ESP32 RX (GPIO16)
Pi GPIO5  (pin 29) ---> ESP32 TX (GPIO17)
Pi GND    (pin 6)  ---> ESP32 GND
```

### ESP32 Motor Pins
```
Motor A (Left Front):  GPIO3, GPIO10
Motor B (Right Front): GPIO11, GPIO12
Motor C (Left Rear):   GPIO13, GPIO14
Motor D (Right Rear):  GPIO21, GPIO47
```

### IR Sensors (5x TCRT5000)
```
W (far left):  GPIO5
NW:            GPIO6
N (center):    GPIO7
NE:            GPIO15
E (far right): GPIO45
```

---

## CODE TESTING CHECKLIST

### Before leaving for demo (test on Pi)
```bash
cd ~/AR-2 && git pull origin main
source .venv/bin/activate

# Start VPN (required for OpenAI/Google APIs in HK)
sudo openvpn --config /etc/openvpn/windscribe.conf --daemon
curl -s https://ipinfo.io/country  # must show SG

# Launch robot
python3 Minilab5/alfred.py --demo --fullscreen --no-ultrasonic
```

### Test sequence (7 steps)
1. **Wake:** Say "Hello Sonny" (or press Wake Up on phone web UI)
   - Expected: face changes, TTS says "I'm listening"
   - Web: http://<pi-ip>:8080 on phone in Chrome

2. **Line follow (R2):** Say "follow the track"
   - Expected: robot follows black tape, stops at end
   - IR sensor dots on web dashboard should light up

3. **Stop:** Say "stop"
   - Expected: immediate halt from any state

4. **ArUco approach (R3):** Say "go to marker 5"
   - Expected: robot rotates searching, finds marker, centers, approaches
   - Should stop ~20cm from marker and HOLD distance
   - Move marker closer → robot backs up
   - Move marker away → robot follows

5. **Obstacle (R4):** Walk in front during ArUco approach
   - Expected: BLOCKED state, then REROUTING (if --enable-yolo)
   - With ultrasonic: immediate stop at <20cm

6. **Chat (EC3):** Say "what is your name"
   - Expected: GPT-4o-mini responds as Sonny the butler

7. **Phone mic:** Repeat step 4 using phone hold-to-talk button
   - Expected: same behavior as USB mic

### Edge cases to test
- Say "stop" before wake phrase — should still stop
- Say "go to marker 99" — should search for any marker (99 > 50)
- Say nonsense — should route to conversation engine
- Cover all IR sensors — line follower should enter LOST recovery
- Block path completely for 15s — should explain itself (after stuck-state fix)

---

## IMPLEMENTATION TASKS (priority order)

### P0: Fix ArUco hold-mode (BUG 4) — CRITICAL for R3
**What:** Stay in ARUCO_APPROACH after reaching 20cm. Let hold-mode handle
back-up and re-approach. Only go IDLE on voice "stop" or 30s idle timeout.
**Where:** `controller.py:1018-1036`

### P1: Fix phone mic wake flow (BUG 1) — CRITICAL for demo
**What:** Check wake phrase before dispatching, wake up, then dispatch the
command-after-wake through `_on_voice_command()`.
**Where:** `web/app.py:449-527`

### P2: Remove NeoPixel UART commands (BUG 6)
**What:** Stop sending `cmd_led()` and `cmd_led_pattern()` over UART.
Keep STATE_LED_COLORS for GUI use.
**Where:** `controller.py:423-439, 361-362, 372-373`

### P3: Fix Google STT sample rate (BUG 5)
**Where:** `listener.py:256`

### P4: Fix web video double-detect (BUG 3)
**Where:** `web/app.py:605-607`

### P5: Fix BLOCKED state for camera-only mode (BUG 7)
**What:** Add camera clear check + minimum 1s blocked duration.
**Where:** `controller.py:1038-1069`

### P6: Add stuck-state OpenAI Vision explanation (R5 enhancement)
**What:** After 15s in BLOCKED or 30s in ARUCO_SEARCH with no detections,
capture frame, send to GPT-4o-mini vision, speak butler-voice explanation.
Rate limit: 1 call per 30s.

### P7: Add line-follow during ArUco search (R3 enhancement)
**What:** If searching for marker and IR sensors see a line, follow the line
while keeping camera scanning. 8s timeout before falling back to rotation.
**Where:** `controller.py:891-945`

---

## DEMO DAY SCRIPT (April 24)

### Setup (arrive 30 min early)
1. Charge 12V battery and phone
2. Connect Pi to venue Wi-Fi (or use phone hotspot)
3. Start VPN: `sudo openvpn --config /etc/openvpn/windscribe.conf --daemon`
4. Verify: `curl -s https://ipinfo.io/country` → SG
5. Lay black tape track on floor
6. Print ArUco markers (DICT_4X4_50, IDs 1-10, 5cm squares)
7. Place markers along/near track
8. Launch: `python3 Minilab5/alfred.py --demo --fullscreen --no-ultrasonic`
9. Open http://<pi-ip>:8080 on phone

### Demo sequence
1. "Hello Sonny" → greeting + face animation
2. "Follow the track" → line following demo
3. "Stop" → immediate halt
4. "Go to marker 5" → search + approach + hold at 20cm
5. Walk in front → obstacle detection + rerouting
6. "What is your name?" → butler conversation
7. "Dance" → dance routine with music
8. "Sleep" → sleep animation

### If things go wrong
- Motors don't work → show web dashboard + explain architecture
- Voice doesn't work → use phone mic or web UI buttons
- Camera lag → `python3 Minilab5/alfred.py --demo --no-ultrasonic` (no YOLO)
- VPN dies → local features still work (line follow, obstacle, dance)
- Total disaster → play pre-recorded demo video (RECORD ONE TONIGHT)
