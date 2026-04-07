#!/usr/bin/env python3
"""NeoPixel LED test — cycle through states and animations."""

import sys
import os
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from alfred.expression.leds import LEDController


def main():
    print("=== NeoPixel LED Test ===\n")

    leds = LEDController()

    print("Cycling through states (1.5s each):")
    for state, color in LEDController.STATE_COLORS.items():
        print(f"  {state}: RGB{color}")
        leds.set_state(state)
        time.sleep(1.5)

    print("\nPulse animation (red, 2s):")
    leds.pulse((255, 0, 0), duration=2.0)
    time.sleep(2.5)

    print("Pulse animation (blue, 2s):")
    leds.pulse((0, 0, 255), duration=2.0)
    time.sleep(2.5)

    print("Rainbow cycle (3s):")
    leds.rainbow_cycle(speed=0.02, duration=3.0)
    time.sleep(3.5)

    print("\nTurning off.")
    leds.off()
    print("Done.")


if __name__ == "__main__":
    main()
