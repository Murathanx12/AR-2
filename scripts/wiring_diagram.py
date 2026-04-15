#!/usr/bin/env python3
"""Generate a visual wiring diagram for Sonny V4 using matplotlib.

Outputs: docs/wiring_diagram.png

Run: python3 scripts/wiring_diagram.py
"""

try:
    import matplotlib
    matplotlib.use('Agg')  # no display needed
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
except ImportError:
    print("matplotlib not installed. Run: pip install matplotlib")
    print("Alternatively, see docs/WIRING.md for text-based diagram.")
    exit(1)

import os

fig, ax = plt.subplots(1, 1, figsize=(18, 12))
ax.set_xlim(0, 18)
ax.set_ylim(0, 12)
ax.set_aspect('equal')
ax.axis('off')
fig.patch.set_facecolor('#0d1117')
ax.set_facecolor('#0d1117')

WHITE = '#c9d1d9'
BLUE = '#58a6ff'
GREEN = '#3fb950'
RED = '#f85149'
YELLOW = '#d29922'
ORANGE = '#f0883e'
PURPLE = '#bc8cff'
DIM = '#484f58'


def box(x, y, w, h, label, color=BLUE, sublabels=None):
    rect = patches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.1",
                                   facecolor='#161b22', edgecolor=color, linewidth=2)
    ax.add_patch(rect)
    ax.text(x + w/2, y + h - 0.25, label, ha='center', va='top',
            fontsize=11, fontweight='bold', color=color)
    if sublabels:
        for i, (txt, clr) in enumerate(sublabels):
            ax.text(x + 0.2, y + h - 0.65 - i*0.35, txt,
                    fontsize=8, color=clr or DIM, family='monospace')


def wire(x1, y1, x2, y2, label="", color=DIM, style='-'):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=1.5, linestyle=style))
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx, my + 0.15, label, fontsize=7, color=color, ha='center',
                bbox=dict(boxstyle='round,pad=0.1', facecolor='#0d1117', edgecolor='none'))


# Title
ax.text(9, 11.5, 'SONNY V4 — Wiring Schematic', ha='center', fontsize=18,
        fontweight='bold', color=BLUE)
ax.text(9, 11.1, 'Project Alfred | HKU School of Innovation', ha='center',
        fontsize=10, color=DIM)

# === RASPBERRY PI 5 ===
box(6.5, 6.5, 5, 3.8, 'RASPBERRY PI 5', BLUE, [
    ('GPIO14 (pin 8)  → TX to ESP32', WHITE),
    ('GPIO15 (pin 10) → RX from ESP32', WHITE),
    ('GPIO2  (pin 3)  → I2C SDA', GREEN),
    ('GPIO3  (pin 5)  → I2C SCL', GREEN),
    ('GND    (pin 6)  → Common GND', DIM),
    ('USB 3.0 → Camera', YELLOW),
    ('USB 2.0 → Mic, Speaker, WiFi', YELLOW),
    ('Micro-HDMI → 14" Monitor', PURPLE),
])

# === ESP32-S3 ===
box(0.5, 1, 7, 4.5, 'ESP32-S3', GREEN, [
    ('GPIO16 (RX) ← from Pi TX', WHITE),
    ('GPIO17 (TX) → to Pi RX', WHITE),
    ('Motors: GPIO 3,10,11,12,13,14,21,47', ORANGE),
    ('IR:     GPIO 5,6,7,15,45', YELLOW),
    ('Ultrasonic: GPIO 4 (trig), 2 (echo)', RED),
    ('NeoPixel:   GPIO 48 (4x WS2812B)', PURPLE),
    ('Buzzer:     GPIO 46', DIM),
    ('Power: 12V battery via car platform', ORANGE),
])

# === MOTORS ===
box(0.5, 6.5, 5.5, 2, 'MECANUM MOTORS', ORANGE, [
    ('FL(A): GPIO 3,10   FR(B): GPIO 11,12', ORANGE),
    ('RL(C): GPIO 13,14  RR(D): GPIO 21,47', ORANGE),
    ('PWM 50-200 | Speed 0-100%', DIM),
])

# === I2C DEVICES ===
box(12, 6.5, 5.5, 1.8, 'I2C DEVICES', GREEN, [
    ('SSD1306 OLED 128x64 @ 0x3C (eyes)', GREEN),
    ('PCA9685 servo board @ 0x40', GREEN),
    ('  ch0=head tilt, ch1-4=arm servos', DIM),
])

# === SENSORS ===
box(8, 1, 4.5, 2.5, 'SENSORS', YELLOW, [
    ('5x TCRT5000 IR (line following)', YELLOW),
    ('  W(5) NW(6) N(7) NE(15) E(45)', DIM),
    ('HC-SR04 ultrasonic (obstacle)', RED),
    ('  Trig(4) Echo(2) ⚠ 3.3V divider', RED),
])

# === USB PERIPHERALS ===
box(12, 1, 5.5, 2.5, 'USB PERIPHERALS', PURPLE, [
    ('USB Camera (video0, 800x600)', PURPLE),
    ('USB Microphone (VOSK STT)', PURPLE),
    ('USB Speaker (espeak-ng TTS)', PURPLE),
    ('USB WiFi adapter (SSH/web)', PURPLE),
])

# === POWER ===
box(12, 4, 5.5, 2, 'POWER', RED, [
    ('12V battery → ESP32 + motors', RED),
    ('LM2596 12V→5V → PCA9685 servos', ORANGE),
    ('5V/5A PSU → Raspberry Pi 5', BLUE),
    ('USB-C PD bank → 14" monitor', PURPLE),
])

# === WIRES ===
# Pi to ESP32 UART
wire(6.5, 8, 5.5, 5.5, 'UART (TX/RX/GND)', BLUE)
# ESP32 to Motors
wire(2, 5.5, 2, 6.5, 'PWM', ORANGE)
# Pi to I2C
wire(11.5, 8, 12, 8, 'I2C', GREEN)
# Pi to USB
wire(11.5, 7, 14, 3.5, 'USB', PURPLE)
# ESP32 to Sensors
wire(7.5, 3, 8, 3, 'GPIO', YELLOW)
# Power
wire(14, 4, 14, 3.5, '', RED, '--')

# Save
out_dir = os.path.join(os.path.dirname(__file__), '..', 'docs')
out_path = os.path.join(out_dir, 'wiring_diagram.png')
plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='#0d1117')
print(f"Saved: {out_path}")
plt.close()
