#!/usr/bin/env python3
"""Sonny V4 — run from project root.

Usage:
    python3 run.py                  # full GUI + phone app
    python3 run.py --headless       # terminal dashboard
    python3 run.py --no-voice       # skip voice
    python3 run.py --no-camera      # skip camera
    python3 run.py --no-web         # skip phone web controller
    python3 run.py --test-vision    # vision test
    python3 run.py --test-voice     # voice test
    python3 run.py --speed 50       # override speed
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import and run
from Minilab5.alfred import main
main()
