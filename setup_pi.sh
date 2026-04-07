#!/usr/bin/env bash
# setup_pi.sh — Raspberry Pi 5 setup for Alfred/Sonny V4
set -euo pipefail

echo "=== Alfred/Sonny V4 — Pi Setup ==="

# System packages
sudo apt-get update
sudo apt-get install -y \
    python3-venv python3-pip \
    python3-opencv \
    libatlas-base-dev \
    i2c-tools \
    espeak-ng \
    ffmpeg \
    portaudio19-dev

# Enable I2C and UART if not already
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_serial_hw 0
sudo raspi-config nonint do_serial_cons 1

# Create and activate venv
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Setup complete. Activate with: source .venv/bin/activate ==="
