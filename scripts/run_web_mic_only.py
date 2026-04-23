#!/usr/bin/env python3
"""Standalone launcher for the web dashboard in mic-only mode.

No FSM, no camera, no UART — just the web server so you can hit
/audio from your phone and see the transcription loop in isolation.
"""
import os
import sys
import socket
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from alfred.web.app import WebController


def lan_ip():
    """Best-effort LAN IP without hitting the network."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def main():
    ip = lan_ip()
    port = 8080
    print(f"\n=== Sonny web dashboard (mic-only test) ===")
    print(f"Open on your phone:  http://{ip}:{port}")
    print(f"(make sure the phone is on the same Wi-Fi as the Pi)")
    print(f"Hit the big 'HOLD TO TALK' button to test the phone mic.")
    print(f"Press Ctrl-C here to stop.\n")

    web = WebController(fsm=None, port=port)
    web.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
