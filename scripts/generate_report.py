#!/usr/bin/env python3
"""Generate Project Alfred technical report as PDF."""

import os
from fpdf import FPDF

OUT_DIR = os.path.join(os.path.dirname(__file__), "..")
OUT_PATH = os.path.join(OUT_DIR, "Project_Alfred_Technical_Brief.pdf")
DIAGRAM_PATH = os.path.join(OUT_DIR, "docs", "wiring_diagram.png")


class Report(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(130, 130, 130)
            self.cell(0, 8, "Project Alfred / Sonny V4  - Technical Brief", align="L")
            self.cell(0, 8, f"Page {self.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")
            self.line(10, 14, 200, 14)
            self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, "HKU School of Innovation | INTC1002 Physical Computing | April 2026", align="C")

    def title_page(self):
        self.add_page()
        self.ln(50)
        self.set_font("Helvetica", "B", 36)
        self.set_text_color(30, 60, 120)
        self.cell(0, 18, "Project Alfred", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(4)
        self.set_font("Helvetica", "", 20)
        self.set_text_color(80, 80, 80)
        self.cell(0, 12, "Sonny V4  - Technical Brief", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(20)
        self.set_font("Helvetica", "", 12)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "Mecanum-Wheeled Robotic Butler", align="C", new_x="LMARGIN", new_y="NEXT")
        self.cell(0, 8, "HKU School of Innovation  - INTC1002", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(10)
        self.cell(0, 8, "Demo Date: April 24, 2026", align="C", new_x="LMARGIN", new_y="NEXT")
        self.cell(0, 8, "Report Date: April 15, 2026", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(30)
        self.set_font("Helvetica", "I", 10)
        self.cell(0, 8, "Repository: github.com/Murathanx12/AR-2", align="C", new_x="LMARGIN", new_y="NEXT")

    def section(self, num, title):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(30, 60, 120)
        self.ln(6)
        self.cell(0, 10, f"{num}. {title}", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def subsection(self, title):
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(50, 80, 130)
        self.ln(3)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body(self, text):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def mono(self, text):
        self.set_font("Courier", "", 9)
        self.set_text_color(50, 50, 50)
        self.set_fill_color(245, 245, 245)
        for line in text.strip().split("\n"):
            self.cell(0, 4.5, "  " + line, new_x="LMARGIN", new_y="NEXT", fill=True)
        self.ln(2)

    def table(self, headers, rows, col_widths=None):
        if col_widths is None:
            col_widths = [190 / len(headers)] * len(headers)
        # Header
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(30, 60, 120)
        self.set_text_color(255, 255, 255)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, h, border=1, fill=True, align="C")
        self.ln()
        # Rows
        self.set_font("Helvetica", "", 9)
        self.set_text_color(40, 40, 40)
        fill = False
        for row in rows:
            if self.get_y() > 265:
                self.add_page()
            if fill:
                self.set_fill_color(240, 245, 255)
            else:
                self.set_fill_color(255, 255, 255)
            max_h = 7
            for i, cell in enumerate(row):
                self.cell(col_widths[i], max_h, str(cell)[:60], border=1, fill=True)
            self.ln()
            fill = not fill
        self.ln(3)

    def bullet(self, text):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        self.set_x(10)
        self.multi_cell(0, 5.5, "  - " + text)

    def check_item(self, text, checked=False):
        mark = "[x]" if checked else "[ ]"
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        self.set_x(10)
        self.multi_cell(0, 5.5, f"  {mark} {text}")


pdf = Report()
pdf.set_auto_page_break(auto=True, margin=20)

# === TITLE PAGE ===
pdf.title_page()

# === 1. PROJECT OVERVIEW ===
pdf.add_page()
pdf.section("1", "Project Overview")
pdf.body(
    "Sonny is a mecanum-wheeled robotic butler built for HKU's Project Alfred competition "
    "(INTC1002 Physical Computing). The robot must respond to voice commands, follow a black "
    "line track to deliver food, navigate to ArUco markers, detect obstacles, and communicate "
    "its intentions through visual, verbal, and audio cues."
)
pdf.body(
    "The system uses a split-brain architecture: a Raspberry Pi 5 handles high-level decision "
    "making (vision, voice, FSM logic, expression) while an ESP32-S3 handles real-time motor "
    "control, sensor reading, and LED/buzzer output. They communicate over a 3-wire UART serial "
    "link at 115200 baud."
)
pdf.body(
    "The demo takes place on April 24, 2026. The robot will be tested in a live 'robot butler' "
    "audition' where the teaching team issues voice commands and the robot must complete tasks "
    "including line-following delivery, ArUco marker approach, and obstacle avoidance."
)

# === 2. ARCHITECTURE ===
pdf.section("2", "System Architecture")
pdf.mono(
    "                  RASPBERRY PI 5                      ESP32-S3\n"
    "              +--------------------+              +-----------------+\n"
    " USB Camera ->| Vision (OpenCV,    |  UART 3-wire | 4x Mecanum      |\n"
    " USB Mic   ->|  MediaPipe, ArUco) |  TX/RX/GND  |   Motors (PWM)  |\n"
    " USB Speaker<-| Voice (VOSK, TTS)  |<----------->| 5x IR Sensors   |\n"
    " 14in Monitor<-| FSM (30Hz, 17    |  115200 baud | HC-SR04 Ultras. |\n"
    " Phone WiFi<->|  states)          |              | 4x NeoPixel LED |\n"
    "              | GUI (Pygame)       |              | Piezo Buzzer    |\n"
    "              | Web Server (Flask) |              |                 |\n"
    "              +--------------------+              +-----------------+\n"
    "              5V/5A PSU                           12V Battery"
)

pdf.subsection("UART Protocol")
pdf.body("Pi to ESP32: mv_vector:vx,vy,omega  |  stop:0  |  led:r,g,b  |  buzzer:freq,ms")
pdf.body("ESP32 to Pi: IR_STATUS:XX (20Hz)  |  DIST:XX.X (10Hz)")

pdf.subsection("Mecanum Inverse Kinematics")
pdf.mono(
    "FL = vx + vy + omega    FR = vx - vy - omega\n"
    "RL = vx - vy + omega    RR = vx + vy - omega\n"
    "Speed 0-100% mapped to PWM 50-200"
)

# === 3. HARDWARE ===
pdf.section("3", "Hardware Inventory")
pdf.subsection("Provided by HKU")
pdf.bullet("Raspberry Pi 5 + 5V/5A PSU + travel adapter + mobile battery + 64GB SD")
pdf.bullet("ESP32-S3 mecanum car platform + 12V battery pack")
pdf.bullet("3x long F-F wires (UART) + USB cable for ESP32 programming")
pdf.bullet("USB camera, USB microphone, USB speaker")

pdf.subsection("Purchased (Additional)")
pdf.table(
    ["Item", "Purpose", "Est. Cost"],
    [
        ["Micro-HDMI to HDMI cable 1m", "Pi 5 to monitor", "20 HKD"],
        ["20000mAh USB-C PD 65W power bank", "Powers 14-inch monitor", "150 HKD"],
        ["USB-C to USB-C PD cable 1m", "Power bank to monitor", "15 HKD"],
        ["4x SG90 9g servos + brackets", "Robot arm (PCA9685 ch1-4)", "55 HKD"],
        ["LM2596 buck converter 12V>5V", "Servo power from battery", "10 HKD"],
        ["HC-SR04 ultrasonic spare", "Backup obstacle sensor", "8 HKD"],
        ["USB WiFi adapter RTL8811AU", "Better WiFi + antenna", "45 HKD"],
        ["USB 3.0 powered hub 4-port", "Extra USB ports", "50 HKD"],
        ["M2/M2.5/M3 bolt+nut+allen set", "Mounting hardware", "35 HKD"],
    ],
    [75, 80, 35],
)

# === 4. WIRING ===
pdf.section("4", "Wiring Diagram")
if os.path.exists(DIAGRAM_PATH):
    pdf.image(DIAGRAM_PATH, x=10, w=190)
    pdf.ln(4)
    pdf.body("Figure 1: Complete wiring schematic (generated from scripts/wiring_diagram.py)")
else:
    pdf.body("[Wiring diagram image not found  - run: python scripts/wiring_diagram.py]")

pdf.subsection("ESP32-S3 Pin Assignments")
pdf.table(
    ["Function", "GPIO Pins"],
    [
        ["Motor A (Front Left)", "3, 10"],
        ["Motor B (Front Right)", "11, 12"],
        ["Motor C (Rear Left)", "13, 14"],
        ["Motor D (Rear Right)", "21, 47"],
        ["IR Sensors (W/NW/N/NE/E)", "5, 6, 7, 15, 45"],
        ["UART RX (from Pi TX)", "16"],
        ["UART TX (to Pi RX)", "17"],
        ["Ultrasonic Trigger", "4"],
        ["Ultrasonic Echo", "2 (needs 3.3V divider)"],
        ["NeoPixel Data (4x WS2812B)", "48"],
        ["Buzzer", "46"],
    ],
    [100, 90],
)

# === 5. SOFTWARE MODULES ===
pdf.add_page()
pdf.section("5", "Software Modules")

pdf.subsection("5.1 FSM Controller (alfred/fsm/)")
pdf.body(
    "The core of the robot is a 17-state finite state machine running at 30Hz. Each tick reads "
    "sensors, dispatches the current state handler, and updates expression subsystems."
)
pdf.table(
    ["State", "Description", "Trigger"],
    [
        ["IDLE", "Waiting for wake word", "Startup / stop command"],
        ["LISTENING", "Awake, waiting for commands", "Wake word detected"],
        ["FOLLOWING", "Line following via IR sensors", "'follow track' command"],
        ["ENDPOINT", "All sensors on line (delivery zone)", "Auto from FOLLOWING"],
        ["PARKING", "Final delivery approach", "Auto from ENDPOINT"],
        ["ARUCO_SEARCH", "Rotating to find ArUco marker", "'go to qr code' command"],
        ["ARUCO_APPROACH", "Driving toward detected marker", "Marker found"],
        ["BLOCKED", "Obstacle detected, halted", "Ultrasonic < 20cm"],
        ["PATROL", "Autonomous wandering", "'patrol' command"],
        ["PERSON_APPROACH", "Approaching detected face", "Face detected in patrol"],
        ["DANCING", "5-second dance routine", "'dance' command"],
        ["PHOTO", "Camera capture", "'photo' command"],
        ["LOST_REVERSE", "Backing up (lost line)", "No IR for 1.2s"],
        ["LOST_PIVOT", "Pivoting (lost line)", "After reverse"],
        ["STOPPING", "Decelerating", "'stop' command"],
        ["SLEEPING", "Low power, needs wake word", "'sleep' command"],
    ],
    [45, 80, 65],
)

pdf.subsection("5.2 Voice System (alfred/voice/)")
pdf.body(
    "VOSK offline STT with grammar-constrained recognition. Wake word 'Hello Sonny' only needed "
    "once  - robot stays awake and treats all subsequent speech as commands. 'stop' works from any "
    "state, even before wake word. Mic auto-mutes during TTS to prevent echo loop."
)
pdf.body("Intent classifier uses exact keyword substring matching. No fuzzy matching (caused false positives).")
pdf.body("Backup: Phone web controller (Flask on port 8080) uses phone's Web Speech API for much better accuracy.")

pdf.subsection("5.3 Vision System (alfred/vision/)")
pdf.body(
    "USB camera at 800x600. ArUco detection (DICT_4X4_50) with visual-only approach using EMA "
    "temporal smoothing. MediaPipe face detection + hand gesture recognition (6 gestures). "
    "Contour-based obstacle detection (disabled for blocking  - too many false positives)."
)

pdf.subsection("5.4 Navigation (alfred/navigation/)")
pdf.body(
    "Line follower: weighted 5-sensor algorithm with turn strengths (-7 to +7), speed-dependent "
    "omega gain, curve slowdown, and lost recovery (reverse + pivot). ArUco approach: proportional "
    "steering on marker center offset, simultaneous steer+drive, creep speed for final approach."
)

pdf.subsection("5.5 Expression System (alfred/expression/)")
pdf.body(
    "OLED SSD1306 128x64 animated eyes with 8 emotions, gaze tracking, auto-blink. NeoPixel LEDs "
    "colored per state. PCA9685 head servo with nod/shake animations. Personality engine maps "
    "FSM state to emotion + LED + head at 10Hz."
)

pdf.subsection("5.6 GUI Dashboard (alfred/gui/)")
pdf.body(
    "1280x720 Pygame window showing: camera feed with detection overlays, OLED eye preview, "
    "IR sensor status, ultrasonic distance, movement vector field, voice I/O display, gesture "
    "recognition, and timestamped event log."
)

pdf.subsection("5.7 Phone Web Controller (alfred/web/)")
pdf.body(
    "Flask server on port 8080 serving an HTML page with mic button (Web Speech API) and quick "
    "command buttons. Phone's built-in STT is far more accurate than VOSK. Uses ~20MB RAM on Pi 5."
)

# === 6. CURRENT ISSUES ===
pdf.add_page()
pdf.section("6", "Current Issues")

pdf.subsection("Issue 1: ESP32 Motors Not Responding (CRITICAL)")
pdf.body(
    "UART connects successfully but motors don't spin. Old artooth firmware also doesn't work. "
    "Nothing was physically changed. Suspected: dead/low 12V battery, chassis short circuit, "
    "loose F-F wires, or motor driver board fault. Diagnostic script created: scripts/test_esp32.py"
)
pdf.body("Impact: Blocks ALL movement tasks (R1-R5, EC1, EC4). Must be fixed first.")

pdf.subsection("Issue 2: Voice Recognition ~50% Accuracy")
pdf.body(
    "VOSK small model (40MB) has limited vocabulary and struggles with accented English. "
    "5-10 second delay between speaking and recognition. Grammar-constrained mode helps "
    "prevent garbage but still misses commands. Phone app built as backup."
)

pdf.subsection("Issue 3: Microphone Quality")
pdf.body(
    "Current USB mic only picks up from ~30cm. Demo requires commands from several meters. "
    "Solutions: USB conference speakerphone (~150 HKD) or phone app relay."
)

pdf.subsection("Issue 4: Camera Obstacle Detection Disabled")
pdf.body(
    "Contour-based detection triggered false BLOCKED states from dark floor patches. "
    "Disabled for FSM blocking. Only ultrasonic HC-SR04 triggers BLOCKED state now."
)

# === 7. LIMITATIONS ===
pdf.section("7", "Limitations by Module")
pdf.table(
    ["Module", "Limitation", "Mitigation"],
    [
        ["VOSK STT", "~50% accuracy, 5-10s delay", "Phone app backup"],
        ["USB Mic", "30cm pickup range", "Phone relay / conference mic"],
        ["ArUco", "No camera calibration", "Pixel-size approach works"],
        ["Line follower", "Arbitrary pseudo-distance", "Tuned empirically"],
        ["Obstacles", "Camera detection disabled", "Ultrasonic only"],
        ["OLED", "128x64 too small to see", "Scaled on 14-inch monitor"],
        ["Servos", "Only head tilt (1 DOF)", "Arm servos future work"],
        ["Conversation", "Needs WiFi + API key", "Canned responses offline"],
    ],
    [40, 75, 75],
)

# === 8. IMPROVEMENTS ===
pdf.section("8", "Improvement Opportunities")
pdf.table(
    ["Improvement", "Effort", "Impact", "Priority"],
    [
        ["Fix ESP32 hardware", "1-2 hours", "Unblocks everything", "P0"],
        ["Test phone app", "10 minutes", "Backup voice input", "P1"],
        ["Buy USB conference mic", "~150 HKD", "Better voice range", "P1"],
        ["Whisper tiny STT", "2-3 hours", "~80% vs 50% accuracy", "P2"],
        ["Camera calibration", "1 hour", "Metric ArUco distance", "P2"],
        ["Robot arm (4x SG90)", "3-4 hours", "EC5 butler tasks", "P3"],
        ["Rerouting (EC2)", "4-5 hours", "Navigate around obstacles", "P3"],
    ],
    [55, 30, 60, 30],
)

# === 9. COMPETITION STATUS ===
pdf.section("9", "Competition Requirements Status")
pdf.table(
    ["Req", "Description", "Code", "Hardware", "Demo Ready"],
    [
        ["R1", "Voice commands", "Done", "Needs mic fix", "Partial"],
        ["R2", "Line following delivery", "Done", "Needs ESP32 fix", "No"],
        ["R3", "ArUco marker approach", "Done", "Needs ESP32 fix", "No"],
        ["R4", "Obstacle detection", "Done", "Needs ultrasonic", "No"],
        ["R5", "Intention indicators", "Done", "Working", "Yes"],
        ["EC1", "Gesture recognition", "Done", "Working", "Yes"],
        ["EC3", "Claude API conversation", "Done", "Needs API key", "Yes"],
        ["EC5", "Butler personality", "Done", "Working", "Yes"],
    ],
    [15, 55, 30, 50, 30],
)

# === 10. CHECKLIST ===
pdf.add_page()
pdf.section("10", "Action Checklist (April 16, 2026)")

pdf.subsection("Priority 1: Hardware")
pdf.check_item("Run python3 scripts/test_esp32.py on the Pi")
pdf.check_item("Measure 12V battery with multimeter (must be >10V)")
pdf.check_item("Check for chassis short circuit (continuity test)")
pdf.check_item("Verify UART wiring: Pi TX(pin8) to ESP32 RX(GPIO16), Pi RX(pin10) to ESP32 TX(GPIO17), GND")
pdf.check_item("If all OK but motors dead: try ESP32 via USB power (isolate battery)")

pdf.subsection("Priority 2: Voice")
pdf.check_item("Install flask: pip install flask")
pdf.check_item("Run python3 run.py, open http://<pi-ip>:8080 on phone")
pdf.check_item("Test each voice command through phone app buttons")
pdf.check_item("Test VOSK mic commands: hello sonny, follow track, go to qr code, stop, dance")

pdf.subsection("Priority 3: Integration Testing")
pdf.check_item("Line following on black tape (R2)")
pdf.check_item("ArUco marker approach with printed marker (R3)")
pdf.check_item("Obstacle detection with HC-SR04 ultrasonic (R4)")
pdf.check_item("Full demo sequence: wake > follow > stop > qr code > stop > dance > sleep")

pdf.subsection("Priority 4: Polish")
pdf.check_item("Tune line follower speed for track conditions")
pdf.check_item("Tune ArUco stop distance")
pdf.check_item("Take photos/video for technical report (due April 30)")

# === 11. PROJECT STRUCTURE ===
pdf.section("11", "Project File Structure")
pdf.mono(
    "AR-2/\n"
    "+-- run.py                 Entry point: python3 run.py\n"
    "+-- TODO.md                Tomorrow's checklist\n"
    "+-- README.md              Project overview\n"
    "+-- CLAUDE.md              AI context for sessions\n"
    "+-- alfred/                Pi Python package\n"
    "|   +-- config.py          All settings\n"
    "|   +-- comms/             UART communication\n"
    "|   +-- fsm/               17-state FSM + controller\n"
    "|   +-- navigation/        Line follow, ArUco, patrol\n"
    "|   +-- vision/            Camera, ArUco, face, hand\n"
    "|   +-- voice/             VOSK STT, intent, TTS\n"
    "|   +-- expression/        Eyes, LEDs, servo, personality\n"
    "|   +-- gui/               Pygame dashboard\n"
    "|   +-- web/               Phone controller (Flask)\n"
    "+-- esp32/src/main.cpp     ESP32 firmware\n"
    "+-- scripts/               Diagnostics + tools\n"
    "+-- docs/                  Wiring, technical docs\n"
    "+-- tests/                 23 unit tests\n"
    "+-- legacy/                Old V1-V3 code"
)

# === SAVE ===
pdf.output(OUT_PATH)
print(f"PDF saved: {OUT_PATH}")
