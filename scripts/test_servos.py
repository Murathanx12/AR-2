#!/usr/bin/env python3
"""Servo + PCA9685 sanity test.

Drives:
  ch0  — head tilt        (range 60..120, center 90)
  ch1  — left shoulder
  ch2  — left elbow
  ch3  — right shoulder
  ch4  — right elbow

Sweep each servo through center → 60° → 120° → center, then run a
wave animation on the right arm and a nod on the head. If you don't
see the PCA9685 at I²C 0x40 the script reports it and exits — fix
the wiring (SDA/SCL/3.3V/GND) before running it again.
"""
import sys
import time
import subprocess

# 1. Confirm I²C bus + PCA9685 first
def i2c_scan(bus=1):
    try:
        out = subprocess.run(["i2cdetect", "-y", str(bus)],
                             capture_output=True, text=True, timeout=2).stdout
    except Exception as e:
        return None, str(e)
    addrs = []
    for line in out.splitlines()[1:]:
        for tok in line.split()[1:]:
            if tok != "--" and tok != "":
                try:
                    addrs.append(int(tok, 16))
                except ValueError:
                    pass
    return addrs, out


print("Scanning I²C bus 1 ...")
addrs, raw = i2c_scan(1)
if addrs is None:
    print(f"i2cdetect not available: {raw}")
    sys.exit(1)
print(f"  devices found: {[hex(a) for a in addrs]}")
have_pca = 0x40 in addrs
if not have_pca:
    print("  ✗ PCA9685 (0x40) NOT detected.")
    print("    Check: VCC->Pi 3.3V (pin 1), GND->Pi GND (pin 6),")
    print("           SDA->Pi SDA GPIO2 (pin 3), SCL->Pi SCL GPIO3 (pin 5).")
    print("           V+ on the servo rail should also be 5V from the LM2596.")
    sys.exit(1)

# 2. Open ServoKit
try:
    from adafruit_servokit import ServoKit
    kit = ServoKit(channels=16)
except Exception as e:
    print(f"\nServoKit init failed: {e}")
    print("  Try: sudo apt install python3-lgpio  OR  pip install lgpio")
    sys.exit(1)

print("\nServoKit ready. Sweeping each channel ...\n")


def sweep(ch, label, low=60, high=120, center=90, step=4, dwell=0.012):
    print(f"  ch{ch} {label}: center → {low}° → {high}° → center")
    try:
        # Center
        kit.servo[ch].angle = center
        time.sleep(0.4)
        # Center → low
        for a in range(center, low - 1, -step):
            kit.servo[ch].angle = a; time.sleep(dwell)
        time.sleep(0.2)
        # low → high
        for a in range(low, high + 1, step):
            kit.servo[ch].angle = a; time.sleep(dwell)
        time.sleep(0.2)
        # high → center
        for a in range(high, center - 1, -step):
            kit.servo[ch].angle = a; time.sleep(dwell)
        time.sleep(0.3)
    except Exception as e:
        print(f"    ✗ ch{ch}: {e}")


CHANNELS = [
    (0, "head tilt"),
    (1, "left shoulder"),
    (2, "left elbow"),
    (3, "right shoulder"),
    (4, "right elbow"),
]
for ch, label in CHANNELS:
    sweep(ch, label)

# 3. Quick FSM-style animations
print("\nRunning wave + nod animations (uses alfred.expression modules) ...")
try:
    sys.path.insert(0, ".")
    from alfred.expression.head import HeadController
    from alfred.expression.arms import ArmController
    arms = ArmController()
    head = HeadController()
    head.nod(amplitude=15, count=2, speed=0.18)
    time.sleep(1.5)
    arms.wave()
    time.sleep(2.5)
    print("  ✓ animations completed")
except Exception as e:
    print(f"  ✗ animation error: {e}")

# 4. Park everything at rest
print("\nParking servos to rest (90°) ...")
for ch, _ in CHANNELS:
    try:
        kit.servo[ch].angle = 90
    except Exception:
        pass
time.sleep(0.5)
print("done.")
