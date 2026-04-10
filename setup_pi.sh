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
    espeak-ng espeak-ng-data \
    ffmpeg \
    portaudio19-dev \
    mbrola mbrola-us1

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

# Download VOSK model if not present
VOSK_MODEL="vosk-model-small-en-us-0.15"
if [ ! -d "$VOSK_MODEL" ]; then
    echo "Downloading VOSK model..."
    wget -q "https://alphacephei.com/vosk/models/$VOSK_MODEL.zip"
    unzip -q "$VOSK_MODEL.zip"
    rm "$VOSK_MODEL.zip"
    echo "VOSK model downloaded to $VOSK_MODEL/"
else
    echo "VOSK model already exists."
fi

echo ""
echo "=== Setup complete ==="
echo "Activate with: source .venv/bin/activate"
echo "Run with: python Minilab5/alfred.py"
echo ""
echo "Optional: For Claude API conversation (EC3):"
echo "  pip install anthropic"
echo "  export ANTHROPIC_API_KEY=your-key-here"
