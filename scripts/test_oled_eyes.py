#!/usr/bin/env python3
"""OLED eye display test — cycle through emotions and gaze positions."""

import sys
import os
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from alfred.expression.eyes import EyeController


def main():
    print("=== OLED Eyes Test ===\n")

    eyes = EyeController()

    print("Cycling through emotions (2s each):")
    for emotion in EyeController.EMOTIONS:
        print(f"  {emotion}")
        eyes.set_emotion(emotion)
        start = time.monotonic()
        while time.monotonic() - start < 2.0:
            eyes.update()
            time.sleep(0.05)

    print("\nTesting gaze tracking:")
    positions = [
        ("center", 0.5, 0.5),
        ("left", 0.0, 0.5),
        ("right", 1.0, 0.5),
        ("up", 0.5, 0.0),
        ("down", 0.5, 1.0),
        ("top-left", 0.0, 0.0),
        ("bottom-right", 1.0, 1.0),
    ]
    eyes.set_emotion("neutral")
    for name, x, y in positions:
        print(f"  Looking {name} ({x}, {y})")
        eyes.look_at(x, y)
        start = time.monotonic()
        while time.monotonic() - start < 1.0:
            eyes.update()
            time.sleep(0.05)

    print("\nTesting blink:")
    for i in range(3):
        print(f"  Blink {i + 1}")
        eyes.blink()
        start = time.monotonic()
        while time.monotonic() - start < 0.5:
            eyes.update()
            time.sleep(0.03)

    frame = eyes.get_frame()
    if frame:
        print(f"\nEye frame generated: {frame.size} pixels")
        try:
            frame.save("eye_test.png")
            print("Saved eye_test.png")
        except Exception:
            pass

    print("\nDone.")


if __name__ == "__main__":
    main()
