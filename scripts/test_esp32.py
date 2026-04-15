#!/usr/bin/env python3
"""ESP32 connection diagnostic — run this on the Raspberry Pi to test UART.

Usage:
    python3 scripts/test_esp32.py

Tests:
  1. Can we open /dev/ttyAMA2?
  2. Is ESP32 sending heartbeat messages?
  3. Are IR sensors responding?
  4. Do motor commands get acknowledged?
  5. Do motors actually spin?
"""

import sys
import time

# ============================================================
# TEST 1: Serial port exists and opens
# ============================================================
print("=" * 60)
print("ESP32 DIAGNOSTIC TEST")
print("=" * 60)
print()

print("[TEST 1] Opening serial port /dev/ttyAMA2...")
try:
    import serial
except ImportError:
    print("  FAIL: pyserial not installed. Run: pip install pyserial")
    sys.exit(1)

PORT = "/dev/ttyAMA2"
BAUD = 115200

try:
    ser = serial.Serial(PORT, BAUD, timeout=2)
    print(f"  OK: Port {PORT} opened at {BAUD} baud")
except Exception as e:
    print(f"  FAIL: {e}")
    print()
    print("  Troubleshooting:")
    print("    1. Is UART2 enabled? Run:")
    print("       grep uart /boot/firmware/config.txt")
    print("       If missing: echo 'dtoverlay=uart2' | sudo tee -a /boot/firmware/config.txt && sudo reboot")
    print("    2. Check port exists: ls -la /dev/ttyAMA*")
    print("    3. Check permissions: sudo usermod -a -G dialout $USER && relogin")
    sys.exit(1)

# ============================================================
# TEST 2: ESP32 heartbeat
# ============================================================
print()
print("[TEST 2] Waiting for ESP32 heartbeat (5 seconds)...")
print("  (ESP32 should send 'Hello from ESP32' every 1.5s)")

heartbeat_found = False
start = time.monotonic()
while time.monotonic() - start < 5.0:
    if ser.in_waiting:
        line = ser.readline().decode(errors='ignore').strip()
        if line:
            print(f"  Received: '{line}'")
            if "hello" in line.lower() or "esp32" in line.lower():
                heartbeat_found = True
            if "IR_STATUS" in line or "DIST:" in line:
                heartbeat_found = True  # sensor data = ESP32 alive

if heartbeat_found:
    print("  OK: ESP32 is alive and sending data")
else:
    print("  FAIL: No data received from ESP32")
    print()
    print("  Troubleshooting:")
    print("    1. Is ESP32 powered? Check 12V battery is ON")
    print("    2. Are UART wires connected?")
    print("       Pi TX (pin 8)  -> ESP32 RX (GPIO16)")
    print("       Pi RX (pin 10) -> ESP32 TX (GPIO17)")
    print("       Pi GND (pin 6) -> ESP32 GND")
    print("    3. Are TX/RX swapped? Try swapping the two data wires")
    print("    4. Is ESP32 firmware flashed? Check on your Windows PC:")
    print("       cd esp32 && pio run --target upload")
    print("    5. Open ESP32 Serial Monitor on PC to verify it boots:")
    print("       pio device monitor --baud 115200")

# ============================================================
# TEST 3: IR sensors
# ============================================================
print()
print("[TEST 3] Reading IR sensors (3 seconds)...")
print("  (Place robot on/off a black line to see changes)")

ir_seen = False
start = time.monotonic()
while time.monotonic() - start < 3.0:
    if ser.in_waiting:
        line = ser.readline().decode(errors='ignore').strip()
        if line.startswith("IR_STATUS:"):
            val = line.split(":")[1]
            bits = int(val) & 0x1F
            sensor_str = "".join(["1" if (bits >> i) & 1 else "0" for i in range(5)])
            print(f"  IR: {sensor_str} (W={sensor_str[0]} NW={sensor_str[1]} N={sensor_str[2]} NE={sensor_str[3]} E={sensor_str[4]})")
            ir_seen = True

if ir_seen:
    print("  OK: IR sensors responding")
else:
    print("  WARN: No IR data received (might be normal if ESP32 not sending)")

# ============================================================
# TEST 4: Send stop command — verify no errors
# ============================================================
print()
print("[TEST 4] Sending 'stop:0' command...")
try:
    ser.write(b"stop:0\n")
    time.sleep(0.5)
    print("  OK: Command sent (no serial error)")
except Exception as e:
    print(f"  FAIL: {e}")

# ============================================================
# TEST 5: Motor test — WILL MOVE THE ROBOT
# ============================================================
print()
print("[TEST 5] Motor test — robot WILL MOVE!")
print()
answer = input("  Type 'go' to test motors (robot will spin briefly): ").strip().lower()

if answer == "go":
    print("  Sending: mv_vector:0,0,30 (slow spin right for 2 seconds)...")
    ser.write(b"mv_vector:0,0,30\n")
    time.sleep(2)
    ser.write(b"stop:0\n")
    print("  Sent stop.")
    print()

    moved = input("  Did the robot spin? (yes/no): ").strip().lower()
    if moved in ("yes", "y"):
        print("  OK: Motors working!")
    else:
        print("  FAIL: Motors not responding to commands")
        print()
        print("  Troubleshooting:")
        print("    1. Is 12V battery charged? Measure with multimeter")
        print("    2. Check motor driver board connections")
        print("    3. Check for short circuits on chassis (metal touching metal)")
        print("    4. Try individual motors:")
        print("       Send 'mv_fwd:50' — should go forward")
        print("       Send 'mv_left:50' — should strafe left")
        print("    5. Check ESP32 Serial Monitor for errors")
        print("    6. Try flashing artooth firmware to isolate software vs hardware")
else:
    print("  Skipped motor test.")

# ============================================================
# TEST 6: Individual motor test
# ============================================================
print()
answer2 = input("  Test each motor individually? (yes/no): ").strip().lower()

if answer2 in ("yes", "y"):
    commands = [
        ("Forward (all motors)",  "mv_fwd:40"),
        ("Reverse (all motors)",  "mv_rev:40"),
        ("Strafe left",           "mv_left:40"),
        ("Strafe right",          "mv_right:40"),
        ("Spin left",             "mv_spinleft:40"),
        ("Spin right",            "mv_spinright:40"),
    ]
    for name, cmd in commands:
        print(f"\n  Testing: {name} ({cmd})")
        input(f"  Press Enter to send '{cmd}'...")
        ser.write(f"{cmd}\n".encode())
        time.sleep(1.5)
        ser.write(b"stop:0\n")
        result = input("  Did it move correctly? (yes/no/skip): ").strip().lower()
        if result == "no":
            print(f"    -> PROBLEM with {name}")

# ============================================================
# SUMMARY
# ============================================================
print()
print("=" * 60)
print("DIAGNOSTIC COMPLETE")
print("=" * 60)
print()
print("If motors don't respond but UART works:")
print("  - Problem is likely hardware (wiring, short circuit, motor driver)")
print("  - Check for metal-on-metal contact on chassis")
print("  - Measure 12V battery voltage")
print("  - Try powering ESP32 via USB (not battery) to isolate power issue")
print()
print("If UART doesn't connect:")
print("  - Check wiring (TX/RX, GND)")
print("  - Check dtoverlay=uart2 in /boot/firmware/config.txt")
print("  - Try: sudo dmesg | grep ttyAMA")

ser.close()
