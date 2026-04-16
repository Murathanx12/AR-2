#!/bin/bash
# Download dance music for Sonny's dance mode
# Place any MP3/WAV file as assets/sounds/dance.mp3 or dance.wav
# The robot will play it during the dance routine

mkdir -p ~/AR-2/assets/sounds

echo "To add dance music:"
echo "  1. Copy any MP3 file to ~/AR-2/assets/sounds/dance.mp3"
echo "  2. Or WAV file to ~/AR-2/assets/sounds/dance.wav"
echo ""
echo "If no music file exists, the robot will use espeak-ng to sing"
echo "'Ai ai ai, I am your little butterfly' in a fun voice."
echo ""
echo "To install MP3 playback: sudo apt-get install mpg123"
echo ""
echo "Example: copy from your phone/laptop via SCP:"
echo "  scp butterfly.mp3 intc1002@192.168.50.9:~/AR-2/assets/sounds/dance.mp3"
