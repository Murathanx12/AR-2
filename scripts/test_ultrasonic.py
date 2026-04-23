#!/usr/bin/env python3
"""Live ultrasonic monitor.

Reads UART from /dev/ttyAMA2 and shows DIST_L / DIST_C / DIST_R
distances at 10Hz. Wave a hand 10-100 cm in front of each sensor;
the value should change smoothly.

If you see ZERO DIST_* messages for a sensor, the wiring on that
sensor is broken — most likely:
  - HC-SR04 not powered (no 5V on VCC)
  - TRIG wire disconnected from ESP32 GPIO
  - ECHO wire not making it through the level shifter to the ESP GPIO
  - Common GND missing (Pi / ESP / sensors must share one ground)

Stop with Ctrl-C.
"""
import sys
import time
import collections
import serial

PORT = "/dev/ttyAMA2"
BAUD = 115200


def main():
    ser = serial.Serial(PORT, BAUD, timeout=0.05)
    print("Listening for ultrasonic readings (Ctrl-C to stop)...\n")
    print(f"{'time':>5}  {'L':>8}  {'C':>8}  {'R':>8}  {'L/s':>5}  {'C/s':>5}  {'R/s':>5}")
    last_vals = {"L": "—", "C": "—", "R": "—"}
    counts = {"L": 0, "C": 0, "R": 0}
    rate_window = collections.deque(maxlen=10)
    buf = b""
    t0 = time.monotonic()
    next_print = t0 + 1.0
    rate_window.append((t0, dict(counts)))

    try:
        while True:
            chunk = ser.read(256)
            if chunk:
                buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                s = line.decode(errors="ignore").strip()
                if s.startswith("DIST_"):
                    side = s[5]               # L / C / R
                    val = s.split(":", 1)[1] if ":" in s else "?"
                    last_vals[side] = val
                    counts[side] = counts.get(side, 0) + 1
            now = time.monotonic()
            if now >= next_print:
                # Compute per-second rates over last second
                rate_window.append((now, dict(counts)))
                t_old, c_old = rate_window[0]
                dt = now - t_old or 1.0
                rates = {k: (counts[k] - c_old.get(k, 0)) / dt for k in counts}
                print(f"{now-t0:5.1f}  {last_vals['L']:>8}  "
                      f"{last_vals['C']:>8}  {last_vals['R']:>8}  "
                      f"{rates['L']:5.1f}  {rates['C']:5.1f}  {rates['R']:5.1f}",
                      flush=True)
                next_print = now + 1.0
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        ser.close()
        print(f"total readings: L={counts['L']}  C={counts['C']}  R={counts['R']}")
        for side in ("L", "C", "R"):
            if counts[side] == 0:
                print(f"  {side}: NO READINGS — sensor wiring failed (see header)")
            else:
                print(f"  {side}: OK ({counts[side]} samples)")


if __name__ == "__main__":
    main()
