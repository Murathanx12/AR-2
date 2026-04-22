"""Alfred V4 debug GUI — Pygame-based dashboard for monitoring and control.

Full-screen layout for the 14" monitor or X11 forwarding.
Shows camera feed with overlays, OLED eyes, sensor data, voice I/O,
gesture recognition, movement vectors, and FSM state.
"""

import math
import time
import logging

logger = logging.getLogger(__name__)

try:
    import pygame
    _HAS_PYGAME = True
except ImportError:
    _HAS_PYGAME = False
    logger.warning("pygame not installed — GUI unavailable")

try:
    import cv2
    import numpy as np
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

from alfred.fsm.states import State, STATE_NAMES


STATE_COLORS = {
    State.IDLE:            (120, 120, 130),
    State.LISTENING:       (100, 100, 255),
    State.FOLLOWING:       (0, 220, 100),
    State.ENDPOINT:        (220, 220, 0),
    State.PARKING:         (50, 100, 220),
    State.ARUCO_SEARCH:    (255, 165, 0),
    State.ARUCO_APPROACH:  (0, 200, 200),
    State.BLOCKED:         (220, 50, 50),
    State.REROUTING:       (220, 130, 50),
    State.PATROL:          (100, 220, 100),
    State.PERSON_APPROACH: (200, 100, 255),
    State.DANCING:         (255, 50, 200),
    State.PHOTO:           (255, 255, 100),
    State.LOST_REVERSE:    (220, 50, 50),
    State.LOST_PIVOT:      (220, 100, 50),
    State.STOPPING:        (180, 180, 180),
    State.SLEEPING:        (60, 60, 80),
}

STATE_DESCRIPTIONS = {
    State.IDLE:            "Standing by — say 'Hello Sonny'",
    State.LISTENING:       "Listening for command...",
    State.FOLLOWING:       "Following the track",
    State.ENDPOINT:        "Reaching destination",
    State.PARKING:         "Parking at delivery zone",
    State.ARUCO_SEARCH:    "Scanning for ArUco marker",
    State.ARUCO_APPROACH:  "Approaching marker",
    State.BLOCKED:         "Obstacle detected! Waiting...",
    State.REROUTING:       "Finding another way",
    State.PATROL:          "Patrolling area",
    State.PERSON_APPROACH: "Approaching person",
    State.DANCING:         "Dancing!",
    State.PHOTO:           "Taking a photo!",
    State.LOST_REVERSE:    "Lost line — reversing",
    State.LOST_PIVOT:      "Lost line — pivoting",
    State.STOPPING:        "Stopping...",
    State.SLEEPING:        "Sleeping — say 'Hello Sonny' to wake",
}


def _pick_font(names, size, bold=False):
    """Pick the first available system font."""
    for name in names:
        try:
            f = pygame.font.SysFont(name, size, bold=bold)
            if f:
                return f
        except Exception:
            continue
    return pygame.font.SysFont(None, size, bold=bold)


class DebugGUI:
    """Full-screen Pygame dashboard for monitoring Sonny.

    Layout (1280x720 or fullscreen):
    ┌──────────────────────┬───────────────────────┐
    │   HEADER: name + state + indicators          │
    ├──────────────────────┬───────────────────────┤
    │                      │                       │
    │   CAMERA FEED        │   EYES + SENSORS      │
    │   (with overlays)    │   + MOVEMENT          │
    │                      │                       │
    ├──────────────────────┴───────────────────────┤
    │   VOICE INPUT | VOICE OUTPUT | GESTURES | LOG│
    └──────────────────────────────────────────────┘
    """

    # Voice command buttons — label, command text, color
    CMD_BUTTONS = [
        ("Wake Up",     "hello sonny",          (30, 100, 250)),
        ("Follow Track","follow track",         (0, 180, 80)),
        ("Any Marker",  "follow the marker",    (200, 160, 0)),
        ("Go Marker 8", "go to marker 8",       (200, 130, 0)),
        ("Follow Me",   "come here",            (140, 80, 220)),
        ("Dance",       "dance",                (220, 50, 180)),
        ("Patrol",      "patrol",               (0, 180, 80)),
        ("Photo",       "photo",                (200, 200, 0)),
        ("Search",      "search",               (0, 160, 200)),
        ("Sleep",       "sleep",                (80, 80, 100)),
        ("STOP",        "stop",                 (220, 40, 40)),
    ]

    def __init__(self, fsm=None, width=900, height=600, fullscreen=False):
        if not _HAS_PYGAME:
            raise RuntimeError("pygame is required for GUI")

        self.fsm = fsm
        self.W = width
        self.H = height
        self._fullscreen = fullscreen
        self._running = False
        self._screen = None
        self._clock = None
        self._fonts = {}

        self._pressed = {'w': False, 's': False, 'a': False, 'd': False, 'q': False, 'e': False}
        self._manual_mode = True

        self._anim_vx = 0.0
        self._anim_vy = 0.0
        self._anim_omega = 0.0

        self._camera_surface = None

        # Voice / event tracking
        self._voice_input = ""
        self._voice_input_time = 0
        self._voice_output = ""
        self._voice_output_time = 0
        self._last_gesture = ""
        self._gesture_time = 0
        self._last_intent = ""
        self._last_confidence = 0.0
        self._event_log = []
        self._detected_markers = []
        self._face_count = 0
        self._hand_count = 0
        self._btn_rects = []  # (pygame.Rect, command_text) for click detection

    def start(self):
        pygame.init()
        if self._fullscreen:
            info = pygame.display.Info()
            self.W, self.H = info.current_w, info.current_h
            self._screen = pygame.display.set_mode((self.W, self.H), pygame.FULLSCREEN)
            pygame.mouse.set_visible(True)
        else:
            self._screen = pygame.display.set_mode((self.W, self.H), pygame.RESIZABLE)
        pygame.display.set_caption("SONNY — Project Alfred Dashboard")
        self._clock = pygame.time.Clock()

        ui_fonts = ["ubuntu", "dejavusans", "segoeui", "freesans", "arial"]
        mono_fonts = ["ubuntumono", "dejavusansmono", "consolas", "freemono", "courier"]
        self._fonts = {
            'title': _pick_font(ui_fonts, 44, bold=True),
            'xl':    _pick_font(ui_fonts, 36, bold=True),
            'lg':    _pick_font(ui_fonts, 28, bold=True),
            'md':    _pick_font(ui_fonts, 22),
            'sm':    _pick_font(ui_fonts, 18),
            'xs':    _pick_font(ui_fonts, 15),
            'mono':  _pick_font(mono_fonts, 20),
            'mono_sm': _pick_font(mono_fonts, 16),
        }
        self._running = True
        self._log("System started")

    def stop(self):
        self._running = False
        if _HAS_PYGAME and pygame.get_init():
            pygame.quit()

    def is_running(self):
        return self._running

    def _log(self, msg):
        self._event_log.append((time.strftime('%H:%M:%S'), msg))
        if len(self._event_log) > 12:
            self._event_log.pop(0)

    def set_voice_input(self, text, intent="", confidence=0.0):
        self._voice_input = text
        self._voice_input_time = time.monotonic()
        self._last_intent = intent
        self._last_confidence = confidence
        if text:
            self._log(f'Heard: "{text}" → {intent} ({confidence:.0%})')

    def set_voice_output(self, text):
        self._voice_output = text
        self._voice_output_time = time.monotonic()
        if text:
            self._log(f'Said: "{text}"')

    def set_gesture(self, gesture):
        if gesture and gesture != "unknown":
            self._last_gesture = gesture
            self._gesture_time = time.monotonic()
            self._log(f'Gesture: {gesture}')

    def set_camera_frame(self, frame):
        if frame is None or not _HAS_PYGAME or not _HAS_CV2:
            self._camera_surface = None
            return

        try:
            display_frame = frame.copy()
            fsm = self.fsm

            # Draw ArUco markers
            if fsm and fsm.aruco_detector:
                markers = fsm.aruco_detector.detect(display_frame)
                self._detected_markers = markers
                for m in markers:
                    pts = m["corners"].astype(int)
                    cv2.polylines(display_frame, [pts], True, (0, 255, 0), 3)
                    cx, cy = int(m["center"][0]), int(m["center"][1])
                    cv2.putText(display_frame, f"ID:{m['id']} sz:{m['size']:.0f}",
                                (cx - 40, cy - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # Draw face boxes
            self._face_count = 0
            if fsm and fsm._last_faces:
                self._face_count = len(fsm._last_faces)
                for face in fsm._last_faces:
                    x, y, w, h = face["bbox"]
                    conf = face.get("confidence", 0)
                    cv2.rectangle(display_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    cv2.putText(display_frame, f"Face {conf:.0%}",
                                (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            # Draw obstacle boxes
            if fsm and fsm._last_obstacles:
                for obs in fsm._last_obstacles:
                    if "bbox" in obs:
                        x, y, w, h = obs["bbox"]
                        cv2.rectangle(display_frame, (x, y), (x + w, y + h), (0, 0, 255), 2)
                        cv2.putText(display_frame, "OBSTACLE",
                                    (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

            # Resize to fit the camera panel
            cam_w = int(self.W * 0.55)
            cam_h = int(self.H * 0.65)
            small = cv2.resize(display_frame, (cam_w, cam_h))
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            self._camera_surface = pygame.surfarray.make_surface(rgb.swapaxes(0, 1))

            # Hand detection count
            self._hand_count = 0
            if fsm and fsm.person_detector and frame is not None:
                try:
                    hands = fsm.person_detector.detect_hands(frame)
                    self._hand_count = len(hands)
                    for hand in hands:
                        gesture = fsm.person_detector.get_gesture(hand)
                        if gesture and gesture != "unknown":
                            self.set_gesture(gesture)
                except Exception:
                    pass
        except Exception as e:
            self._camera_surface = None

    def update(self):
        if not self._running or not _HAS_PYGAME:
            return False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
                return False
            elif event.type == pygame.KEYDOWN:
                self._handle_keydown(event.key)
            elif event.type == pygame.KEYUP:
                self._handle_keyup(event.key)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._handle_click(event.pos)
            elif event.type == pygame.VIDEORESIZE:
                self.W, self.H = event.w, event.h
                self._screen = pygame.display.set_mode((self.W, self.H), pygame.RESIZABLE)

        fsm = self.fsm
        state = fsm.state if fsm else State.IDLE
        lf = fsm.line_follower if fsm else None
        uart = fsm.uart if fsm else None
        now = time.monotonic()

        bits = [0, 0, 0, 0, 0]
        dists = {"left": -1.0, "center": -1.0, "right": -1.0}
        if uart and uart.is_open:
            bits = uart.get_ir_bits()
            dists = uart.get_distances()

        debug_vx = lf.debug_vx if lf else 0
        debug_vy = lf.debug_vy if lf else 0
        debug_omega = lf.debug_omega if lf else 0

        lerp = 0.25
        self._anim_vx += (debug_vx - self._anim_vx) * lerp
        self._anim_vy += (debug_vy - self._anim_vy) * lerp
        self._anim_omega += (debug_omega - self._anim_omega) * lerp

        # Track voice input from listener
        if fsm and fsm.voice_listener:
            vtext = fsm.voice_listener.last_text
            if vtext and vtext != self._voice_input:
                self.set_voice_input(vtext)

        # === RENDER ===
        BG = (16, 18, 24)
        PANEL = (26, 30, 38)
        BORDER = (40, 45, 58)
        DIM = (70, 75, 90)
        self._screen.fill(BG)

        W, H = self.W, self.H
        PAD = 8
        HEADER_H = 60
        BOTTOM_H = 160
        CAM_W = int(W * 0.55)
        RIGHT_W = W - CAM_W - PAD * 3
        MIDDLE_H = H - HEADER_H - BOTTOM_H - PAD * 3

        # ============ HEADER ============
        pygame.draw.rect(self._screen, (28, 32, 42), (0, 0, W, HEADER_H))
        pygame.draw.line(self._screen, BORDER, (0, HEADER_H), (W, HEADER_H))

        self._screen.blit(self._fonts['title'].render("SONNY", True, (70, 160, 255)), (PAD + 8, 8))

        # State
        st_color = STATE_COLORS.get(state, (180, 180, 180))
        st_name = STATE_NAMES.get(state, '?')
        st_desc = STATE_DESCRIPTIONS.get(state, "")
        st_surf = self._fonts['xl'].render(st_name, True, st_color)
        self._screen.blit(st_surf, (W - st_surf.get_width() - PAD - 8, 2))
        desc_surf = self._fonts['sm'].render(st_desc, True, (140, 145, 160))
        self._screen.blit(desc_surf, (W - desc_surf.get_width() - PAD - 8, 36))

        # Mode pill
        mode_label = "AUTO" if not self._manual_mode else "MANUAL"
        mode_color = (0, 220, 100) if not self._manual_mode else (220, 180, 0)
        pill = self._fonts['md'].render(mode_label, True, mode_color)
        px = 180
        pygame.draw.rect(self._screen, mode_color, (px, 16, pill.get_width() + 16, 28), 1, border_radius=14)
        self._screen.blit(pill, (px + 8, 18))

        # Mic + Lang
        mic_on = fsm and fsm.voice_listener is not None
        mic_color = (0, 200, 255) if mic_on else (60, 60, 70)
        mic_x = px + pill.get_width() + 40
        self._screen.blit(self._fonts['sm'].render("MIC ON" if mic_on else "MIC OFF", True, mic_color), (mic_x, 20))
        lang = "EN"
        if fsm and fsm.voice_listener:
            lang = fsm.voice_listener.language.upper()
        self._screen.blit(self._fonts['sm'].render(f"| {lang}", True, (100, 160, 255)), (mic_x + 70, 20))

        # ============ MIDDLE LEFT: CAMERA ============
        cam_x = PAD
        cam_y = HEADER_H + PAD
        pygame.draw.rect(self._screen, PANEL, (cam_x, cam_y, CAM_W, MIDDLE_H), border_radius=10)
        pygame.draw.rect(self._screen, BORDER, (cam_x, cam_y, CAM_W, MIDDLE_H), 1, border_radius=10)

        if self._camera_surface:
            cr = self._camera_surface.get_rect()
            bx = cam_x + (CAM_W - cr.width) // 2
            by = cam_y + (MIDDLE_H - cr.height) // 2
            self._screen.blit(self._camera_surface, (bx, by))

            # Overlay detection counts on the camera panel
            overlay_y = cam_y + MIDDLE_H - 30
            det_parts = []
            if self._detected_markers:
                ids = ", ".join(str(m["id"]) for m in self._detected_markers)
                det_parts.append(f"ArUco: [{ids}]")
            if self._face_count:
                det_parts.append(f"Faces: {self._face_count}")
            if self._hand_count:
                det_parts.append(f"Hands: {self._hand_count}")
            if det_parts:
                det_text = "  |  ".join(det_parts)
                det_bg = pygame.Surface((CAM_W - 4, 26), pygame.SRCALPHA)
                det_bg.fill((0, 0, 0, 160))
                self._screen.blit(det_bg, (cam_x + 2, overlay_y))
                self._screen.blit(self._fonts['sm'].render(det_text, True, (0, 255, 100)), (cam_x + 10, overlay_y + 3))
        else:
            no_cam = self._fonts['lg'].render("No Camera Feed", True, (50, 50, 60))
            self._screen.blit(no_cam, (cam_x + CAM_W // 2 - no_cam.get_width() // 2,
                                       cam_y + MIDDLE_H // 2 - 14))
            hint = self._fonts['xs'].render("Check USB camera or run with --no-camera", True, DIM)
            self._screen.blit(hint, (cam_x + CAM_W // 2 - hint.get_width() // 2,
                                     cam_y + MIDDLE_H // 2 + 16))

        # ============ MIDDLE RIGHT: Eyes + Sensors + Vector ============
        right_x = cam_x + CAM_W + PAD
        right_y = cam_y

        # -- Eyes panel (top right) --
        eye_h = int(MIDDLE_H * 0.35)
        pygame.draw.rect(self._screen, PANEL, (right_x, right_y, RIGHT_W, eye_h), border_radius=10)
        pygame.draw.rect(self._screen, BORDER, (right_x, right_y, RIGHT_W, eye_h), 1, border_radius=10)

        if fsm and fsm.eyes:
            eye_frame = fsm.eyes.get_frame()
            if eye_frame:
                try:
                    pil_img = eye_frame.convert('L') if eye_frame.mode == '1' else eye_frame
                    ew, eh = pil_img.size
                    raw = pil_img.tobytes()
                    sc = st_color
                    rgb_data = bytearray(ew * eh * 3)
                    for i, px in enumerate(raw):
                        b = px / 255.0
                        rgb_data[i*3] = int(sc[0] * b)
                        rgb_data[i*3+1] = int(sc[1] * b)
                        rgb_data[i*3+2] = int(sc[2] * b)
                    esrf = pygame.image.frombuffer(bytes(rgb_data), (ew, eh), 'RGB')
                    sf = min((RIGHT_W - 16) / ew, (eye_h - 8) / eh)
                    scaled = pygame.transform.scale(esrf, (int(ew * sf), int(eh * sf)))
                    self._screen.blit(scaled, (right_x + (RIGHT_W - int(ew * sf)) // 2,
                                               right_y + (eye_h - int(eh * sf)) // 2))
                except Exception:
                    self._draw_simple_eyes(right_x, right_y, RIGHT_W, eye_h, state)
            else:
                self._draw_simple_eyes(right_x, right_y, RIGHT_W, eye_h, state)
        else:
            self._draw_simple_eyes(right_x, right_y, RIGHT_W, eye_h, state)

        # -- Sensors panel (IR + 3x Ultrasonic) --
        ir_y = right_y + eye_h + PAD
        ir_h = int(MIDDLE_H * 0.38)
        pygame.draw.rect(self._screen, PANEL, (right_x, ir_y, RIGHT_W, ir_h), border_radius=10)
        pygame.draw.rect(self._screen, BORDER, (right_x, ir_y, RIGHT_W, ir_h), 1, border_radius=10)
        self._screen.blit(self._fonts['xs'].render("IR SENSORS", True, DIM), (right_x + 10, ir_y + 4))

        sensor_names = ['W', 'NW', 'N', 'NE', 'E']
        spacing = RIGHT_W // 6
        ir_btn_y = ir_y + 22
        for i in range(5):
            sx = right_x + spacing * (i + 1) - 20
            sy = ir_btn_y
            on = bits[i]
            color = (0, 220, 80) if on else (42, 46, 56)
            bc = (0, 255, 80) if on else (55, 60, 72)
            pygame.draw.rect(self._screen, color, (sx, sy, 40, 24), border_radius=6)
            pygame.draw.rect(self._screen, bc, (sx, sy, 40, 24), 1, border_radius=6)
            lbl = self._fonts['xs'].render(sensor_names[i], True, (255, 255, 255) if on else (80, 80, 90))
            self._screen.blit(lbl, (sx + 20 - lbl.get_width() // 2, sy + 4))

        # -- Ultrasonic 3x display --
        us_label_y = ir_btn_y + 32
        self._screen.blit(self._fonts['xs'].render("ULTRASONIC", True, DIM), (right_x + 10, us_label_y))

        us_names = ['L', 'C', 'R']
        us_keys = ['left', 'center', 'right']
        bar_max_w = RIGHT_W - 80
        bar_h = 16
        bar_x = right_x + 30
        bar_start_y = us_label_y + 18

        for idx, (name, key) in enumerate(zip(us_names, us_keys)):
            by = bar_start_y + idx * (bar_h + 6)
            d = dists[key]

            # Label
            self._screen.blit(self._fonts['xs'].render(name, True, (150, 155, 170)),
                              (right_x + 10, by + 1))

            # Background bar
            pygame.draw.rect(self._screen, (34, 38, 48), (bar_x, by, bar_max_w, bar_h), border_radius=4)

            if d > 0:
                # Fill bar — scale 0-200cm to full width, clamp at 200
                fill_frac = min(d / 200.0, 1.0)
                fill_w = max(2, int(bar_max_w * fill_frac))
                if d < 20:
                    bar_color = (220, 50, 50)
                    border_color = (255, 60, 60)
                elif d < 50:
                    bar_color = (220, 160, 30)
                    border_color = (255, 190, 40)
                else:
                    bar_color = (0, 180, 90)
                    border_color = (0, 220, 100)
                pygame.draw.rect(self._screen, bar_color, (bar_x, by, fill_w, bar_h), border_radius=4)
                pygame.draw.rect(self._screen, border_color, (bar_x, by, fill_w, bar_h), 1, border_radius=4)

                # Distance text
                dtxt = f"{d:.0f}cm"
                if d < 20:
                    dtxt += " !"
                dl = self._fonts['xs'].render(dtxt, True, (255, 255, 255))
                self._screen.blit(dl, (bar_x + bar_max_w + 4, by + 1))
            else:
                dl = self._fonts['xs'].render("---", True, (60, 60, 70))
                self._screen.blit(dl, (bar_x + bar_max_w + 4, by + 1))

        # -- Movement vector panel --
        vec_y = ir_y + ir_h + PAD
        vec_h = MIDDLE_H - eye_h - ir_h - PAD * 2
        pygame.draw.rect(self._screen, PANEL, (right_x, vec_y, RIGHT_W, vec_h), border_radius=10)
        pygame.draw.rect(self._screen, BORDER, (right_x, vec_y, RIGHT_W, vec_h), 1, border_radius=10)
        self._screen.blit(self._fonts['xs'].render("MOVEMENT", True, DIM), (right_x + 10, vec_y + 4))

        # Vector viz
        viz_cx = right_x + RIGHT_W // 4
        viz_cy = vec_y + vec_h // 2 + 5
        viz_r = min(RIGHT_W // 4 - 10, vec_h // 2 - 16)
        if viz_r > 10:
            for rf in [0.5, 1.0]:
                pygame.draw.circle(self._screen, (34, 38, 48), (viz_cx, viz_cy), int(viz_r * rf), 1)
            pygame.draw.line(self._screen, (34, 38, 48), (viz_cx - viz_r, viz_cy), (viz_cx + viz_r, viz_cy))
            pygame.draw.line(self._screen, (34, 38, 48), (viz_cx, viz_cy - viz_r), (viz_cx, viz_cy + viz_r))

            bot = 7
            pygame.draw.rect(self._screen, (55, 60, 75), (viz_cx - bot, viz_cy - bot, bot*2, bot*2), border_radius=3)

            arrow_scale = viz_r / 150
            ax = self._anim_vy * arrow_scale
            ay = -self._anim_vx * arrow_scale
            if math.sqrt(ax*ax + ay*ay) > 2:
                ac = (80, 220, 130) if self._anim_vx > 0 else (220, 80, 80) if self._anim_vx < -3 else (80, 160, 255)
                self._draw_arrow(self._screen, ac, (viz_cx, viz_cy), (viz_cx + int(ax), viz_cy + int(ay)), 2, 8)

        # Numeric readout
        tx = right_x + RIGHT_W // 2 + 10
        self._screen.blit(self._fonts['mono'].render(f"vx:   {debug_vx:+4d}", True, (100, 220, 130)), (tx, vec_y + 20))
        self._screen.blit(self._fonts['mono'].render(f"vy:   {debug_vy:+4d}", True, (100, 160, 255)), (tx, vec_y + 42))
        self._screen.blit(self._fonts['mono'].render(f"omega:{debug_omega:+4d}", True, (220, 180, 60)), (tx, vec_y + 64))

        # ============ BOTTOM: Voice I/O + Commands + Log ============
        bot_y = HEADER_H + PAD + MIDDLE_H + PAD
        bot_h = BOTTOM_H - PAD

        # Divide bottom into 3 columns
        col_w = (W - PAD * 4) // 3

        # -- Voice Input --
        c1x = PAD
        pygame.draw.rect(self._screen, PANEL, (c1x, bot_y, col_w, bot_h), border_radius=10)
        pygame.draw.rect(self._screen, BORDER, (c1x, bot_y, col_w, bot_h), 1, border_radius=10)
        self._screen.blit(self._fonts['sm'].render("VOICE INPUT", True, DIM), (c1x + 10, bot_y + 6))

        if self._voice_input and now - self._voice_input_time < 10:
            heard = self._fonts['md'].render(f'"{self._voice_input}"', True, (0, 200, 255))
            self._screen.blit(heard, (c1x + 10, bot_y + 30))
            if self._last_intent:
                intent_color = (0, 220, 100) if self._last_confidence > 0.8 else (220, 180, 0)
                self._screen.blit(self._fonts['sm'].render(
                    f"Intent: {self._last_intent} ({self._last_confidence:.0%})", True, intent_color),
                    (c1x + 10, bot_y + 58))
            # Detection + gesture summary
            det_items = []
            if self._face_count: det_items.append(f"Faces:{self._face_count}")
            if self._hand_count: det_items.append(f"Hands:{self._hand_count}")
            if self._last_gesture and now - self._gesture_time < 5:
                det_items.append(f"Gesture:{self._last_gesture}")
            if self._detected_markers:
                det_items.append("Markers:" + ",".join(str(m["id"]) for m in self._detected_markers))
            if det_items:
                self._screen.blit(self._fonts['xs'].render("  ".join(det_items), True, (100, 180, 100)),
                                (c1x + 10, bot_y + bot_h - 22))
        else:
            engine = "none"
            if self.fsm and self.fsm.voice_listener:
                engine = self.fsm.voice_listener.engine
            self._screen.blit(self._fonts['sm'].render(f"Waiting for voice... ({engine})", True, (50, 55, 65)),
                            (c1x + 10, bot_y + 40))

        # -- Command Buttons (clickable fallback for voice) --
        c2x = c1x + col_w + PAD
        pygame.draw.rect(self._screen, PANEL, (c2x, bot_y, col_w, bot_h), border_radius=10)
        pygame.draw.rect(self._screen, BORDER, (c2x, bot_y, col_w, bot_h), 1, border_radius=10)
        self._screen.blit(self._fonts['xs'].render("COMMANDS (click or use voice)", True, DIM), (c2x + 8, bot_y + 4))

        self._btn_rects = []
        btn_cols = 4
        btn_rows = 3
        btn_pad = 3
        btn_area_x = c2x + 6
        btn_area_y = bot_y + 22
        btn_area_w = col_w - 12
        btn_area_h = bot_h - 28
        bw = (btn_area_w - btn_pad * (btn_cols - 1)) // btn_cols
        bh = (btn_area_h - btn_pad * (btn_rows - 1)) // btn_rows

        for idx, (label, cmd_text, color) in enumerate(self.CMD_BUTTONS):
            row = idx // btn_cols
            col = idx % btn_cols
            if row >= btn_rows:
                break
            bx = btn_area_x + col * (bw + btn_pad)
            by = btn_area_y + row * (bh + btn_pad)
            # STOP button spans 2 columns if it's the last one
            this_bw = bw
            if label == "STOP":
                this_bw = bw
            rect = pygame.Rect(bx, by, this_bw, bh)
            self._btn_rects.append((rect, cmd_text))

            # Draw button
            pygame.draw.rect(self._screen, color, rect, border_radius=5)
            pygame.draw.rect(self._screen, (min(255, color[0]+40), min(255, color[1]+40), min(255, color[2]+40)),
                           rect, 1, border_radius=5)
            lbl = self._fonts['xs'].render(label, True, (255, 255, 255))
            self._screen.blit(lbl, (bx + (this_bw - lbl.get_width()) // 2,
                                    by + (bh - lbl.get_height()) // 2))

        # -- Event Log --
        c3x = c2x + col_w + PAD
        c3w = W - c3x - PAD
        pygame.draw.rect(self._screen, PANEL, (c3x, bot_y, c3w, bot_h), border_radius=10)
        pygame.draw.rect(self._screen, BORDER, (c3x, bot_y, c3w, bot_h), 1, border_radius=10)
        self._screen.blit(self._fonts['sm'].render("EVENT LOG", True, DIM), (c3x + 10, bot_y + 6))

        log_y = bot_y + 26
        for ts, msg in self._event_log[-7:]:
            line = f"{ts} {msg}"
            if self._fonts['mono_sm'].size(line)[0] > c3w - 20:
                while self._fonts['mono_sm'].size(line + "...")[0] > c3w - 20 and len(line) > 10:
                    line = line[:-1]
                line += "..."
            self._screen.blit(self._fonts['mono_sm'].render(line, True, (100, 105, 120)), (c3x + 10, log_y))
            log_y += 17

        # Keyboard hint at bottom
        hint = self._fonts['xs'].render(
            "WASD=move  QE=turn  Space=STOP  M=mode  F11=fullscreen  1/2=speed  ESC=quit", True, (50, 55, 65))
        self._screen.blit(hint, (PAD + 10, H - 18))

        pygame.display.flip()
        self._clock.tick(30)
        return True

    def _draw_simple_eyes(self, rx, ry, rw, rh, state):
        sc = STATE_COLORS.get(state, (120, 120, 130))
        left_cx = rx + rw // 3
        right_cx = rx + 2 * rw // 3
        cy = ry + rh // 2

        if state == State.SLEEPING:
            ew, eh = 50, 8
        elif state == State.BLOCKED:
            ew, eh = 56, 24
        elif state in (State.DANCING, State.PERSON_APPROACH):
            ew, eh = 50, 42
        else:
            ew, eh = 46, 38

        for cx in (left_cx, right_cx):
            pygame.draw.ellipse(self._screen, sc, (cx - ew // 2, cy - eh // 2, ew, eh))
            pr = max(5, min(ew, eh) // 5)
            pygame.draw.ellipse(self._screen, (16, 18, 24), (cx - pr, cy - pr, pr * 2, pr * 2))

    def _handle_click(self, pos):
        """Handle mouse click on command buttons."""
        for rect, cmd_text in self._btn_rects:
            if rect.collidepoint(pos):
                self._log(f"Button: {cmd_text}")
                if self.fsm:
                    self.fsm._on_voice_command(cmd_text)
                    # Wake up if needed
                    if self.fsm.voice_listener and not self.fsm.voice_listener.is_awake:
                        from alfred.voice.listener import WAKE_VARIANTS
                        for wake in WAKE_VARIANTS:
                            if wake in cmd_text.lower():
                                self.fsm.voice_listener._do_wake(
                                    cmd_text.lower().split(wake, 1)[-1].strip()
                                )
                                break
                break

    def _handle_keydown(self, key):
        from alfred.comms.protocol import cmd_vector, cmd_stop
        fsm = self.fsm
        lf = fsm.line_follower if fsm else None

        if key == pygame.K_F11:
            # Toggle fullscreen
            if self._screen.get_flags() & pygame.FULLSCREEN:
                self._screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
                self.W, self.H = 1280, 720
                pygame.mouse.set_visible(True)
            else:
                info = pygame.display.Info()
                self.W, self.H = info.current_w, info.current_h
                self._screen = pygame.display.set_mode((self.W, self.H), pygame.FULLSCREEN)
                pygame.mouse.set_visible(False)
            return
        elif key == pygame.K_m:
            self._manual_mode = not self._manual_mode
            self._pressed = {k: False for k in self._pressed}
            if fsm:
                if self._manual_mode:
                    fsm.transition(State.IDLE)
                    fsm.uart.send(cmd_stop())
                else:
                    fsm.transition(State.FOLLOWING)
                    if lf: lf.reset()
            self._log(f"Mode: {'MANUAL' if self._manual_mode else 'AUTO'}")
        elif key == pygame.K_f:
            if fsm:
                self._manual_mode = False
                fsm.transition(State.FOLLOWING)
                if lf: lf.reset()
            self._log("Started line following")
        elif key == pygame.K_SPACE:
            self._pressed = {k: False for k in self._pressed}
            if fsm:
                fsm.uart.send(cmd_stop())
                fsm.transition(State.IDLE)
            self._manual_mode = True
            self._log("EMERGENCY STOP")
        elif key == pygame.K_ESCAPE:
            self._running = False
        elif key == pygame.K_1:
            if lf: lf.current_speed = max(10, lf.current_speed - 5)
            self._update_manual_movement()
        elif key == pygame.K_2:
            if lf: lf.current_speed = min(150, lf.current_speed + 5)
            self._update_manual_movement()
        elif key in (pygame.K_w, pygame.K_s, pygame.K_a, pygame.K_d, pygame.K_q, pygame.K_e):
            km = {pygame.K_w: 'w', pygame.K_s: 's', pygame.K_a: 'a',
                  pygame.K_d: 'd', pygame.K_q: 'q', pygame.K_e: 'e'}
            self._pressed[km[key]] = True
            self._update_manual_movement()

    def _handle_keyup(self, key):
        km = {pygame.K_w: 'w', pygame.K_s: 's', pygame.K_a: 'a',
              pygame.K_d: 'd', pygame.K_q: 'q', pygame.K_e: 'e'}
        if key in km:
            self._pressed[km[key]] = False
            self._update_manual_movement()

    def _update_manual_movement(self):
        if not self._manual_mode or not self.fsm:
            return
        from alfred.comms.protocol import cmd_vector, cmd_stop
        lf = self.fsm.line_follower
        speed = lf.current_speed if lf else 35
        vx, vy, omega = 0, 0, 0
        if self._pressed['w']: vx += speed
        if self._pressed['s']: vx -= speed
        if self._pressed['a']: vy -= speed
        if self._pressed['d']: vy += speed
        if self._pressed['q']: omega -= speed
        if self._pressed['e']: omega += speed
        if lf:
            lf.debug_vx, lf.debug_vy, lf.debug_omega = vx, vy, omega
        if vx == 0 and vy == 0 and omega == 0:
            self.fsm.uart.send(cmd_stop())
        else:
            self.fsm.uart.send(cmd_vector(vx, vy, omega))

    @staticmethod
    def _draw_arrow(surface, color, start, end, width=2, head_size=8):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.sqrt(dx * dx + dy * dy)
        if length < 3:
            return
        pygame.draw.line(surface, color, start, end, width)
        angle = math.atan2(dy, dx)
        left = (end[0] - head_size * math.cos(angle - 0.5),
                end[1] - head_size * math.sin(angle - 0.5))
        right = (end[0] - head_size * math.cos(angle + 0.5),
                 end[1] - head_size * math.sin(angle + 0.5))
        pygame.draw.polygon(surface, color, [end, left, right])
