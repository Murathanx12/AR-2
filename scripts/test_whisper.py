#!/usr/bin/env python3
"""Whisper STT test — record audio and transcribe."""

import sys
import os
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from alfred.voice.listener import VoiceListener
from alfred.voice.intent import IntentClassifier


def main():
    print("=== Whisper STT Test ===")
    print("Say something after the prompt. Press Ctrl+C to stop.\n")

    classifier = IntentClassifier()

    def on_speech(text):
        intent, conf = classifier.classify(text)
        print(f"  Heard: '{text}'")
        print(f"  Intent: {intent} (confidence: {conf:.1f})")
        print()

    listener = VoiceListener(wake_phrase="hello sonny")
    listener.on_speech(on_speech)
    listener.start()

    print("Listening... (say 'Hello Sonny' followed by a command)")
    try:
        while True:
            if listener.is_wake_word_detected():
                print("  >>> Wake word detected!")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
    print("\nDone.")


if __name__ == "__main__":
    main()
