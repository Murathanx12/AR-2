#!/usr/bin/env python3
"""Piper TTS test — synthesize and play speech."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from alfred.voice.speaker import Speaker


def main():
    print("=== TTS Test ===\n")

    speaker = Speaker()

    print("Testing predefined phrases:")
    for key, phrase in Speaker.PHRASES.items():
        print(f"  [{key}]: {phrase}")
        speaker.say_sync(key)
        print()

    print("\nTesting custom text:")
    custom = "Hello! I am Sonny, your robotic butler. How may I assist you today?"
    print(f"  '{custom}'")
    speaker.say_sync(custom)

    print("\nDone.")


if __name__ == "__main__":
    main()
