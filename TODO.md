# TODO — Demo Day Prep (April 24, 2026)

Last updated: April 23, 2026 — all pre-demo code work landed. Ready for full ground-up test.

## STATUS: CODE FROZEN FOR DEMO — READY FOR OVERALL TEST

Everything we built over the 2026-04-23 session is now in main:
- ArUco calibrated at 1080p native (PHYSICAL_MARKER_M=0.18, FOCAL_RATIO=0.413)
- Camera default resolution is 1920×1080 (preserves full 160° FOV; 720p hardware-crops)
- Photo gallery saves to photos/, web /photos route, voice intent `show_photos`
- Voice pipeline: OpenAI Realtime WebSocket + gpt-4o-mini-transcribe is primary, with batch Whisper fallback and faster-whisper local fallback. No head-of-line blocking; "stop" is always heard.
- Hallucination filter + homophone normalizer in place (market→marker, sony→sonny, etc).
- Phone web mic also upgraded to gpt-4o-mini-transcribe with same filter.
- NeoPixel references removed everywhere.
- **OLED removed** — no SSD1306 in the build, eyes render only to the on-monitor face GUI. ExpressionConfig now only carries `eye_width`/`eye_height`; `eyes.py` no longer imports adafruit_ssd1306.
- **Single ultrasonic** — only the center HC-SR04 is wired. Firmware (`esp32/src/main.cpp`) trimmed to read center pin only at 10 Hz; boot banner now reads `ESP32 Ready (V4.1 — center ultrasonic only + buzzer)` so we can tell from UART which version is flashed. Re-flash required: `cd esp32 && pio run --target upload`.

### Resolved bugs (what was fixed, and where)
| # | Bug | Status | Fix |
|---|-----|--------|-----|
| 1 | Phone mic did not wake robot | RESOLVED | `web/app.py` /audio now auto-wakes Pi listener and strips wake phrase before dispatch |
| 2 | Phone mic double intent classification | RESOLVED | single classify pass per phone utterance |
| 3 | Web video re-ran ArUco detection | RESOLVED | `/video_feed` uses `fsm._last_markers` cache |
| 4 | ArUco approach exited to IDLE on arrival (no hold-mode) | RESOLVED | FSM stays in ARUCO_APPROACH, hold-mode back-up / re-approach logic keeps ticking |
| 5 | Google STT wrong sample rate | RESOLVED by removal | Google STT path disabled — OpenAI Whisper is the only cloud STT (user-requested) |
| 6 | NeoPixel UART commands wasted bandwidth | RESOLVED | `cmd_led` / `cmd_led_pattern` no longer sent from FSM; STATE_LED_COLORS kept for GUI only |
| 7 | BLOCKED flicker in camera-only mode | RESOLVED | camera clear check + 1 s minimum blocked duration |
| 8 | Stale NeoPixel comment in firmware | RESOLVED | removed from `esp32/src/main.cpp` |
| new | ArUco marker size was 5 cm constant, real tag is 18 cm | RESOLVED | `PHYSICAL_MARKER_M = 0.18` in `aruco_approach.py:39` |
| new | Photos cluttered repo root | RESOLVED | robot now saves to `photos/` folder with timestamped filenames |

## NEW FEATURE: Photo gallery
- Photos saved to `photos/photo_YYYYMMDD_HHMMSS.jpg`.
- `/photos` on the web dashboard renders a gallery (newest first, shows "taken" timestamp).
- `/photos.json` for programmatic access, `/photo/<name>` serves individual images.
- Gallery is loaded **on demand only** — the main dashboard never embeds it. Triggers:
  - Voice: "show me picture", "show me photos", "open gallery", "show the gallery"
  - Button: "Gallery" button in Voice Commands panel opens `/photos` in new tab
  - Direct URL: `http://<pi-ip>:8080/photos`
- Voice intent `show_photos` announces the gallery URL through the speaker.

## MIC PRIORITY (clarified)
- **Pi USB microphone is the PRIMARY input** — runs on its own continuous listener thread.
- **Phone web mic is a BACKUP** — `/audio` endpoint on the web dashboard, hold-to-talk.
- Phone mic does not mute, disable, or block the Pi mic. If the same utterance is
  transcribed by both within 3 s, the phone mic request is dropped as a duplicate.
- Removed Google STT — all cloud STT is now OpenAI Whisper only.

## ArUco calibration (18 cm tag) — test plan
The user will run the following test BEFORE any motion test:

1. Launch with camera + UART + no motion requested:
   ```
   python3 Minilab5/alfred.py --no-ultrasonic
   ```
2. Hold the 18 cm ArUco marker 20 cm in front of camera.
   - Expected: logs show `dist ≈ 0.20 m`. Stop/hold logic would engage if motion were enabled.
3. Hold the same marker 30 cm in front.
   - Expected: logs show `dist ≈ 0.30 m`, matches `HOLD_FAR_M`.
4. If reading is consistently off by a fixed ratio, tune `FOCAL_RATIO`:
   `FOCAL_RATIO = measured_pixel_size * known_distance_m / (0.18 * frame_width)`

### The pinhole model (updated for 18 cm tag)
```
distance_m = (0.18 * 0.8 * frame_width) / pixel_size
```
At 1920 px width and 20 cm distance, expected pixel size ≈ 1382 px (fills most of frame).
At 1920 px width and 50 cm distance, expected pixel size ≈ 553 px.
At 1920 px width and 1.0 m distance, expected pixel size ≈ 276 px.

## TEST ORDER (agreed with user)
1. **Camera + ArUco distance** — hold 18 cm marker at 20 cm, then 30 cm. No motion.
2. **Pi mic + speaker (local only)**
   - TTS test: `espeak-ng "Hello I am Sonny"` in terminal.
   - Speech-to-text: speak "Hello Sonny, what time is it" at Pi mic. Check Whisper output.
   - Text-to-speech from FSM: trigger via voice, verify speaker says "I'm listening".
3. **Website as backup mic**
   - Open `http://<pi-ip>:8080` on phone.
   - Hold-to-talk: "go to marker 5". Confirm transcription + intent fire.
   - Confirm Pi mic still works after phone mic round-trip.
4. **Full R1–R5 run-through** — only after 1–3 pass.

## DEMO DAY RUNBOOK
1. Charge 12 V battery, phone, monitor battery pack.
2. `sudo openvpn --config /etc/openvpn/windscribe.conf --daemon`
3. `curl -s https://ipinfo.io/country` → SG
4. `python3 Minilab5/alfred.py --demo --fullscreen --no-ultrasonic`
5. Phone: open `http://<pi-ip>:8080`
6. Demo sequence:
   - "Hello Sonny" → greeting + face
   - "Follow the track" → R2 line following
   - "Stop" → immediate halt
   - "Go to marker 5" → R3 search + approach + hold at 20 cm (18 cm tag)
   - Walk in front → R4 obstacle detection + rerouting
   - "What is your name?" → EC3 butler chat
   - "Take a photo" → saves to `photos/`
   - "Show me the picture" → announces gallery URL (or tap Gallery button)
   - "Dance" → routine
   - "Sleep" → sleep animation

## HARDWARE NOT WIRED (known, handled in software)
- Ultrasonic sensors (HC-SR04 × 3) — not wired. Camera-based obstacle detection
  (`--no-ultrasonic` flag) is the primary path. YOLO + contour fallback handle R4.
- NeoPixel LEDs — removed.
- Motors — pending ESP32 hardware verification (`scripts/test_esp32.py`).

## WIRING REFERENCE

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

## KEY COMMANDS
```bash
# Pull latest and launch
cd ~/AR-2 && git pull origin main
source .venv/bin/activate
sudo openvpn --config /etc/openvpn/windscribe.conf --daemon
python3 Minilab5/alfred.py --demo --fullscreen --no-ultrasonic

# Diagnostics
python3 scripts/test_esp32.py
python3 scripts/test_aruco.py
python3 scripts/test_whisper.py
python3 scripts/test_tts.py

# Photo gallery (phone browser)
http://<pi-ip>:8080/photos
```
