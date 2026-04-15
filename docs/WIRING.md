# Sonny V4 — Complete Wiring Schematic

## ESP32-S3 Pin Map

```
ESP32-S3 GPIO Pin Assignments
═══════════════════════════════════════════════════

MOTORS (8 pins — motor driver board)
─────────────────────────────────────
  Motor A (Left Front):   GPIO 3  (DIR1), GPIO 10 (DIR2/PWM)
  Motor B (Right Front):  GPIO 11 (DIR1), GPIO 12 (DIR2/PWM)
  Motor C (Left Rear):    GPIO 13 (DIR1), GPIO 14 (DIR2/PWM)
  Motor D (Right Rear):   GPIO 21 (DIR1), GPIO 47 (DIR2/PWM)

IR SENSORS (5 pins — TCRT5000 reflective sensors)
──────────────────────────────────────────────────
  Sensor 1 (W  — far left):     GPIO 5
  Sensor 2 (NW — left-center):  GPIO 6
  Sensor 3 (N  — center front): GPIO 7
  Sensor 4 (NE — right-center): GPIO 15
  Sensor 5 (E  — far right):    GPIO 45

UART to Raspberry Pi (2 pins)
─────────────────────────────
  ESP32 RX:  GPIO 16  ←── Pi TX (GPIO14, physical pin 8)
  ESP32 TX:  GPIO 17  ──→ Pi RX (GPIO15, physical pin 10)
  GND:       GND      ←→  Pi GND (physical pin 6)

ULTRASONIC HC-SR04 (2 pins)
────────────────────────────
  Trigger:  GPIO 4
  Echo:     GPIO 2   ⚠ Needs 5V→3.3V voltage divider!

NEOPIXEL LEDs (1 pin)
─────────────────────
  Data:  GPIO 48   (WS2812B, 4 LEDs)

BUZZER (1 pin)
──────────────
  Signal:  GPIO 46  (Piezo buzzer)
```

## Raspberry Pi 5 Pin Map

```
Pi 5 GPIO Header (relevant pins only)
═══════════════════════════════════════

  Pin 1  (3.3V)    → OLED VCC, PCA9685 VCC
  Pin 3  (GPIO 2)  → I2C SDA → OLED SDA + PCA9685 SDA
  Pin 5  (GPIO 3)  → I2C SCL → OLED SCL + PCA9685 SCL
  Pin 6  (GND)     → ESP32 GND + OLED GND + PCA9685 GND
  Pin 8  (GPIO14)  → Pi TX → ESP32 RX (GPIO16)    [UART2]
  Pin 9  (GND)     → OLED/PCA9685 GND
  Pin 10 (GPIO15)  → Pi RX → ESP32 TX (GPIO17)    [UART2]

USB Ports:
  USB 3.0 (blue)   → Camera
  USB 2.0 (black)  → Microphone
  USB 2.0 (black)  → Speaker
  USB 2.0 (black)  → WiFi adapter (or via USB hub)

Micro-HDMI:
  Port 0 → HDMI cable → 14" monitor
```

## UART Wiring (3 wires between Pi and ESP32)

```
  Raspberry Pi 5              ESP32-S3
  ┌──────────┐                ┌──────────┐
  │  TX (pin 8, GPIO14) ───────→ RX (GPIO16) │
  │  RX (pin10, GPIO15) ←──────── TX (GPIO17) │
  │  GND (pin 6)        ←──────→ GND          │
  └──────────┘                └──────────┘

  Baud: 115200, 8N1
  Protocol: text commands "name:param1,param2\n"
```

## I2C Bus (daisy-chained)

```
  Pi SDA (pin 3) ──┬── OLED SDA (0x3C)
                   └── PCA9685 SDA (0x40)

  Pi SCL (pin 5) ──┬── OLED SCL
                   └── PCA9685 SCL
```

## Power Distribution

```
  12V Battery ──→ ESP32 car platform (motors + ESP32)
              ──→ LM2596 buck converter ──→ 5V ──→ PCA9685 V+ (servos)

  Pi 5V/5A PSU ──→ Raspberry Pi 5

  USB-C PD power bank ──→ 14" monitor
```

## Motor Layout (Top View)

```
        FRONT (camera + IR sensors)
    ┌─────────────────────────┐
    │  FL(A)            FR(B) │
    │  GPIO 3,10    GPIO 11,12│
    │                         │
    │       [Pi 5 + OLED]     │
    │       [Camera on top]   │
    │                         │
    │  RL(C)            RR(D) │
    │  GPIO 13,14   GPIO 21,47│
    └─────────────────────────┘
         REAR

  Mecanum IK:
    FL = vx + vy + omega
    FR = vx - vy - omega
    RL = vx - vy + omega
    RR = vx + vy - omega
```
