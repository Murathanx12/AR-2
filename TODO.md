# TODO — Next Session (7 days to demo)

## PRIORITY 0: Motor Hardware (BLOCKS EVERYTHING)
- [ ] Measure 12V battery voltage with multimeter — must be >10V
- [ ] If battery dead: charge it or try different battery
- [ ] If battery OK: check motor driver board connections to ESP32
- [ ] Try: power ESP32 via USB (laptop) while 12V powers motors separately
- [ ] Try: connect one motor directly to 12V to verify motors themselves work
- [ ] Check chassis for short circuit (continuity test between motor wires and metal frame)

## PRIORITY 1: Camera Feed Fix
- [ ] Check web dashboard frame size (bottom-left of camera shows "WxH")
- [ ] If 800x600 but looks cropped: camera is physically rotated or offset
- [ ] Try different USB port for camera
- [ ] Try lowering resolution in config.py (640x480)

## PRIORITY 2: Portable Monitor
- [ ] Bring a USB keyboard to plug into Pi directly
- [ ] Close remote desktop, log in on the physical HDMI monitor
- [ ] Run from local terminal: python3 Minilab5/alfred.py --no-web

## PRIORITY 3: Full Integration Test (after motors work)
- [ ] Line following on black tape — "follow track"
- [ ] ArUco approach — "go to marker 8" (hold printed marker)
- [ ] Verify centering behavior (should stop rotation, face marker, then approach)
- [ ] Verify hold distance (should stop and follow if marker moves)
- [ ] Test "go to marker 42" to switch targets
- [ ] Dance with butterfly music — "dance"
- [ ] Follow human — "come here"
- [ ] Obstacle detection with ultrasonic

## PRIORITY 4: Polish
- [ ] Add more ArUco marker IDs to web UI
- [ ] Show robot face/eyes on portable monitor
- [ ] Take demo video for technical report
- [ ] Test full demo sequence: wake → track → stop → marker → dance → sleep

## Quick Reference
```bash
cd ~/AR-2 && git pull origin main
source .venv/bin/activate
python3 Minilab5/alfred.py --headless    # web dashboard at :8080
python3 scripts/test_esp32.py            # motor diagnostic
cat logs/sonny.log                       # check event log
```
