# Sonny V4 — Test Checklist

Use this checklist before the demo (April 24, 2026) to verify all features.
Run each test on the Raspberry Pi with VPN connected.

## Pre-flight

- [ ] VPN connected: `curl -s https://ipinfo.io/country` shows SG
- [ ] `.env` has OPENAI_API_KEY set
- [ ] `.env` has ANTHROPIC_API_KEY set (optional, for EC3 chat)
- [ ] Camera plugged into Pi USB port directly (not hub)
- [ ] Mic plugged into Pi USB port directly (not hub)
- [ ] Speaker connected (USB hub OK)
- [ ] ESP32 powered on, 12V battery charged
- [ ] UART wires connected (TX→RX, RX→TX, GND→GND)
- [ ] Monitor connected via micro-HDMI

## R1: Voice Commands

### STT Engine
- [ ] OpenAI Whisper API works: say something, check log shows `openai-api`
- [ ] Google STT fallback: disconnect VPN briefly, verify Google or Whisper local kicks in
- [ ] Phone mic relay: open http://<pi-ip>:8080, hold-to-talk, verify transcription

### Wake Word
- [ ] "Hello Sonny" → robot wakes up, says greeting
- [ ] "Hello Sunny" → also works
- [ ] "Hey Sonny" → also works
- [ ] Robot stays awake after wake word (no need to repeat)
- [ ] "Sleep" → robot goes to sleep, needs wake word again

### Voice Commands (say after waking)
- [ ] "Follow the track" → enters FOLLOWING state
- [ ] "Go to marker 5" → enters ARUCO_SEARCH, targets marker 5
- [ ] "Go to QR code" → enters ARUCO_SEARCH, targets any marker
- [ ] "Find marker forty two" → targets marker 42 (word number)
- [ ] "Go to marker 12" → targets marker 12
- [ ] "Dance" → enters DANCING state
- [ ] "Take a photo" → captures photo
- [ ] "Come here" → enters PERSON_APPROACH
- [ ] "Patrol" → enters PATROL
- [ ] "Stop" → stops immediately from any state
- [ ] "Search" → enters ARUCO_SEARCH
- [ ] Unknown phrase → auto-routes to Claude chat (if API available)

### Smart Intent (GPT-4o-mini)
- [ ] "Can you follow the line please" → follow_track
- [ ] "I need you to go to code number 8" → go_to_aruco, marker=8
- [ ] "Let's see you dance" → dance
- [ ] "What's your name?" → chat (routed to Claude)

## R2: Line Following

- [ ] ESP32 motors respond to UART commands (test with scripts/test_esp32.py)
- [ ] IR sensors reading correctly (check web dashboard or headless view)
- [ ] Robot follows a black line on white surface
- [ ] Robot handles curves (slows down on sharp turns)
- [ ] Robot detects endpoint (all 5 sensors on)
- [ ] Robot recovers when lost (reverse → pivot)

## R3: ArUco Marker Approach

- [ ] Camera detects ArUco markers (DICT_4X4_50, IDs 0-49)
- [ ] "Go to marker 8" → robot scans, finds marker 8, approaches
- [ ] Robot centers on marker (lateral correction)
- [ ] Robot stops at correct distance (STOP_SIZE ~140px)
- [ ] Robot announces "Found marker X, approaching" via TTS
- [ ] Robot announces arrival with beep
- [ ] Marker IDs visible on camera overlay (debug GUI or web)

## R4: Obstacle Detection

- [ ] Ultrasonic HC-SR04 sends DIST readings (check UART log)
- [ ] Robot stops when obstacle < 20cm during FOLLOWING
- [ ] Robot stops when obstacle < 20cm during ARUCO_APPROACH
- [ ] Robot resumes when obstacle removed
- [ ] LED turns red + blink pattern when BLOCKED
- [ ] TTS says "Obstacle detected"

## R5: Intention Indicators

### LEDs (NeoPixel)
- [ ] IDLE: dim blue
- [ ] FOLLOWING: green
- [ ] ARUCO_SEARCH: yellow breathe
- [ ] BLOCKED: red blink
- [ ] DANCING: rainbow cycle
- [ ] SLEEPING: dim blue breathe

### TTS Announcements
- [ ] State transitions trigger voice announcements
- [ ] "Following the track" when entering FOLLOWING
- [ ] "Searching for the marker" when entering ARUCO_SEARCH
- [ ] "Obstacle detected" when entering BLOCKED
- [ ] "Time to dance!" when entering DANCING

### Buzzer
- [ ] Beep on line-follow completion (1000Hz)
- [ ] Beep on ArUco arrival (1200Hz)
- [ ] Shutter sound on photo (1500Hz)

### OLED Eyes
- [ ] 8 emotions display correctly (run scripts/test_oled_eyes.py)
- [ ] Eyes change with FSM state
- [ ] Auto-blink every ~4 seconds
- [ ] Gaze tracking works

## EC1: Gesture Recognition

- [ ] MediaPipe installed: `python -c "import mediapipe"`
- [ ] Open palm → stop (during patrol)
- [ ] Thumbs up → come here
- [ ] Peace sign → take photo
- [ ] Point → follow track

## EC2: Autonomous Rerouting

- [ ] Obstacle avoider computes avoidance vector
- [ ] Robot attempts to go around obstacle (basic)

## EC3: Natural Conversation

- [ ] Say something conversational → Claude responds as Sonny the butler
- [ ] Responses are 1-2 sentences, spoken via TTS
- [ ] Butler personality: British formality, witty, helpful

## EC4: Autonomous Patrol

- [ ] "Patrol" → robot wanders randomly
- [ ] Detects people and approaches them
- [ ] Reacts to gestures during patrol
- [ ] Avoids obstacles while patrolling

## EC5: Butler Personality

### Demo GUI Face (14" monitor)
- [ ] `python3 Minilab5/alfred.py --demo` shows fullscreen face
- [ ] Eyes animate with emotions matching FSM state
- [ ] Eyes blink automatically
- [ ] Gaze moves naturally (random idle, scanning during search)
- [ ] Mouth changes with emotion (smile, frown, O, line)
- [ ] Status bar shows current state + description
- [ ] Voice transcript appears at bottom-right
- [ ] Intent + confidence shown
- [ ] Camera PiP in corner with ArUco overlay
- [ ] Rainbow border during dance
- [ ] ESC quits, F11 toggles fullscreen

### Arm Servos (cosmetic)
- [ ] Wave animation on greeting/person approach
- [ ] Carry pose during line following
- [ ] Point forward during ArUco search
- [ ] Dance arms during DANCING
- [ ] Shrug when BLOCKED
- [ ] Rest position in IDLE

## Web Dashboard

- [ ] Accessible at http://<pi-ip>:8080
- [ ] Live camera feed with overlays
- [ ] All sensor data updating (IR, ultrasonic, movement)
- [ ] Command buttons work (Wake Up, Follow Track, etc.)
- [ ] Keyboard drive works (WASD + QE + Space)
- [ ] Phone mic hold-to-talk works
- [ ] Marker ID input (1-50) works
- [ ] Event log shows state changes and voice commands

## OpenAI Vision Scene Analyzer

- [ ] Scene analysis triggers during patrol/search states
- [ ] Log shows scene descriptions
- [ ] Rate-limited (min 5 seconds between analyses)
- [ ] `describe_scene()` returns butler-style scene description

## Unit Tests

```bash
python -m pytest tests/ -v
```
- [ ] test_intent.py — all intent classifications pass
- [ ] test_protocol.py — all UART commands format correctly
- [ ] test_bev.py — bird's eye view transforms work
- [ ] test_path_planner.py — path planning works

## Demo Day Procedure

1. Power on Pi + ESP32 + monitor
2. Connect VPN: `sudo openvpn --config /etc/openvpn/windscribe.conf --daemon`
3. Verify: `curl -s https://ipinfo.io/country` → SG
4. Start Sonny: `cd ~/AR-2 && source .venv/bin/activate && python3 Minilab5/alfred.py --demo`
5. Open phone browser to http://<pi-ip>:8080 (backup mic + controls)
6. Say "Hello Sonny" → robot wakes up
7. Ready for commands from teaching team
