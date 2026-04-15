# TODO — April 16, 2026 (8 days to demo)

## PRIORITY 1: Hardware (must fix first — nothing works without this)

- [ ] **Run ESP32 diagnostic** — `python3 scripts/test_esp32.py`
  - Check if UART receives ESP32 heartbeat
  - Check if motors respond to commands
  - If no heartbeat: check wiring, battery, TX/RX swap
  - If heartbeat but no motors: check 12V battery voltage, motor driver, chassis short

- [ ] **Check 12V battery** — measure with multimeter, must be >10V

- [ ] **Check for chassis short circuit** — multimeter continuity mode between motor wires and metal frame

- [ ] **Verify UART wiring matches docs/WIRING.md**
  - Pi TX (pin 8, GPIO14) → ESP32 RX (GPIO16)
  - Pi RX (pin 10, GPIO15) → ESP32 TX (GPIO17)
  - Pi GND (pin 6) → ESP32 GND

- [ ] **Test with artooth firmware** — if alfred firmware doesn't work, flash artooth to isolate software vs hardware

## PRIORITY 2: Voice (critical for R1 demo)

- [ ] **Test phone app** — `pip install flask` then run `python3 run.py`, open `http://<pi-ip>:8080` on phone
  - Phone buttons should work immediately (no wake word needed)
  - Phone mic button should be very accurate (uses Chrome STT)
  - This is the backup plan if VOSK mic fails during demo

- [ ] **Test VOSK commands** — say each command, note which ones work/fail:
  - [ ] "Hello Sonny" → wakes up
  - [ ] "follow track" → line following
  - [ ] "go to qr code" → ArUco search
  - [ ] "stop" → stops (works from any state)
  - [ ] "dance" → dance routine
  - [ ] "photo" → take photo
  - [ ] "patrol" → autonomous wander
  - [ ] "sleep" → go to sleep

- [ ] **Consider better microphone** — USB conference speakerphone (~150 HKD on Taobao) if budget allows

## PRIORITY 3: Integration Testing (after hardware works)

- [ ] **Line following (R2)** — place robot on black tape, say "follow track", verify it follows
- [ ] **ArUco approach (R3)** — print ArUco marker (DICT_4X4_50), say "go to qr code", robot should find and approach it
- [ ] **Obstacle detection (R4)** — connect HC-SR04 ultrasonic, put hand in front during R2/R3, verify BLOCKED state
- [ ] **Intention indicators (R5)** — verify NeoPixel LEDs change color per state, TTS announces state changes
- [ ] **Gesture recognition (EC1)** — during patrol, show hand gestures to camera
- [ ] **Butler conversation (EC3)** — set ANTHROPIC_API_KEY, say "chat", verify Claude responds

## PRIORITY 4: Polish (after everything works)

- [ ] **Tune line follower speed** — adjust `--speed` parameter for track conditions
- [ ] **Tune ArUco stop distance** — adjust `stop_size` in config if robot stops too far/close
- [ ] **Test full demo sequence** — wake → follow track → stop → go to qr code → stop → dance → sleep
- [ ] **Take photos/video for technical report** (due April 30)
- [ ] **GUI cosmetics** — verify it looks good on the 14" monitor

## FUTURE (after demo, if time)

- [ ] Whisper tiny STT (better accuracy than VOSK, runs on Pi 5)
- [ ] Robot arm with SG90 servos (PCA9685 ch1-4)
- [ ] Autonomous rerouting (EC2)
- [ ] Patrol with waypoints (EC4)

## Quick Reference

```bash
# Pull latest code
cd ~/AR-2 && git pull origin main

# Run with GUI
python3 run.py

# Run headless (SSH)
python3 run.py --headless

# Test ESP32
python3 scripts/test_esp32.py

# Phone control
# Open http://<pi-ip>:8080 on phone after starting run.py
```
