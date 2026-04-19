"""Demo face GUI — fullscreen animated robot face for the 14" monitor.

Layout (1920x1080 fullscreen):
┌──────────────────────────────────────────────┐
│                                              │
│          ████████      ████████              │
│          ██    ██      ██    ██              │
│          ████████      ████████     [cam PiP]│
│                                              │
├──────────────────────────────────────────────┤
│  STATE: Following track    │  "go to marker 5"│
│  ████████████░░░░░░░░░░    │  Intent: aruco   │
└──────────────────────────────────────────────┘
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

try:
    import cv2
    import numpy as np
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

from alfred.fsm.states import State, STATE_NAMES


STATE_COLORS = {
    State.IDLE:            (100, 140, 220),
    State.LISTENING:       (80, 160, 255),
    State.FOLLOWING:       (0, 220, 100),
    State.ENDPOINT:        (220, 220, 0),
    State.PARKING:         (50, 180, 220),
    State.ARUCO_SEARCH:    (255, 200, 0),
    State.ARUCO_APPROACH:  (0, 220, 200),
    State.BLOCKED:         (255, 60, 60),
    State.REROUTING:       (255, 130, 50),
    State.PATROL:          (100, 220, 100),
    State.PERSON_APPROACH: (200, 100, 255),
    State.DANCING:         (255, 80, 220),
    State.PHOTO:           (255, 255, 100),
    State.LOST_REVERSE:    (255, 100, 50),
    State.LOST_PIVOT:      (255, 130, 50),
    State.STOPPING:        (180, 180, 180),
    State.SLEEPING:        (40, 40, 60),
}

STATE_DESCRIPTIONS = {
    State.IDLE:            "Standing by — say 'Hello Sonny'",
    State.LISTENING:       "Listening for your command...",
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
    State.SLEEPING:        "Sleeping — say 'Hello Sonny'",
}

EMOTION_FROM_STATE = {
    State.IDLE:            "neutral",
    State.LISTENING:       "surprised",
    State.FOLLOWING:       "happy",
    State.ENDPOINT:        "happy",
    State.PARKING:         "happy",
    State.ARUCO_SEARCH:    "confused",
    State.ARUCO_APPROACH:  "happy",
    State.BLOCKED:         "angry",
    State.REROUTING:       "confused",
    State.PATROL:          "neutral",
    State.PERSON_APPROACH: "love",
    State.DANCING:         "happy",
    State.PHOTO:           "surprised",
    State.LOST_REVERSE:    "sad",
    State.LOST_PIVOT:      "confused",
    State.STOPPING:        "neutral",
    State.SLEEPING:        "sleepy",
}


def _pick_font(names, size, bold=False):
    for name in names:
        try:
            f = pygame.font.SysFont(name, size, bold=bold)
            if f:
                return f
        except Exception:
            continue
    return pygame.font.SysFont(None, size, bold=bold)


class DemoGUI:
    """Fullscreen robot face for the demo monitor.

    Big animated eyes (60% of screen), status bar at bottom,
    camera PiP in corner, voice transcript overlay.
    """

    def __init__(self, fsm=None, fullscreen=True):
        if not _HAS_PYGAME:
            raise RuntimeError("pygame is required for GUI")
        self.fsm = fsm
        self._fullscreen = fullscreen
        self._running = False
        self._screen = None
        self._clock = None
        self._fonts = {}
        self.W, self.H = 1920, 1080

        self._camera_surface = None
        self._voice_input = ""
        self._voice_input_time = 0
        self._voice_output = ""
        self._voice_output_time = 0
        self._last_intent = ""
        self._last_confidence = 0.0
        self._detected_markers = []

        # Eye animation state
        self._gaze_x = 0.5
        self._gaze_y = 0.5
        self._target_gaze_x = 0.5
        self._target_gaze_y = 0.5
        self._blink_state = 0.0
        self._last_blink = time.monotonic()
        self._blink_time = 0
        self._idle_gaze_time = time.monotonic()

    def start(self):
        pygame.init()
        if self._fullscreen:
            info = pygame.display.Info()
            self.W, self.H = info.current_w, info.current_h
            self._screen = pygame.display.set_mode((self.W, self.H), pygame.FULLSCREEN)
            pygame.mouse.set_visible(False)
        else:
            self._screen = pygame.display.set_mode((self.W, self.H), pygame.RESIZABLE)
        pygame.display.set_caption("SONNY")
        self._clock = pygame.time.Clock()

        ui = ["ubuntu", "dejavusans", "segoeui", "freesans", "arial"]
        mono = ["ubuntumono", "dejavusansmono", "consolas", "freemono", "courier"]
        self._fonts = {
            'title':  _pick_font(ui, 64, bold=True),
            'state':  _pick_font(ui, 48, bold=True),
            'desc':   _pick_font(ui, 32),
            'voice':  _pick_font(ui, 36, bold=True),
            'intent': _pick_font(ui, 28),
            'sm':     _pick_font(ui, 22),
            'xs':     _pick_font(ui, 18),
            'mono':   _pick_font(mono, 24),
        }
        self._running = True

    def stop(self):
        self._running = False
        if _HAS_PYGAME and pygame.get_init():
            pygame.quit()

    def is_running(self):
        return self._running

    def set_voice_input(self, text, intent="", confidence=0.0):
        self._voice_input = text
        self._voice_input_time = time.monotonic()
        self._last_intent = intent
        self._last_confidence = confidence

    def set_voice_output(self, text):
        self._voice_output = text
        self._voice_output_time = time.monotonic()

    def set_gesture(self, gesture):
        pass

    def set_camera_frame(self, frame):
        if frame is None or not _HAS_CV2:
            self._camera_surface = None
            return
        try:
            display_frame = frame.copy()
            fsm = self.fsm

            if fsm and fsm.aruco_detector:
                markers = fsm.aruco_detector.detect(display_frame)
                self._detected_markers = markers
                for m in markers:
                    pts = m["corners"].astype(int)
                    cv2.polylines(display_frame, [pts], True, (0, 255, 0), 3)
                    cx, cy = int(m["center"][0]), int(m["center"][1])
                    cv2.putText(display_frame, f"ID:{m['id']}",
                                (cx - 30, cy - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

            pip_w, pip_h = 320, 180
            small = cv2.resize(display_frame, (pip_w, pip_h))
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            self._camera_surface = pygame.surfarray.make_surface(rgb.swapaxes(0, 1))
        except Exception:
            self._camera_surface = None

    def update(self):
        if not self._running or not _HAS_PYGAME:
            return False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
                return False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self._running = False
                    return False
                elif event.key == pygame.K_F11:
                    if self._screen.get_flags() & pygame.FULLSCREEN:
                        self._screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
                        self.W, self.H = 1280, 720
                        pygame.mouse.set_visible(True)
                    else:
                        info = pygame.display.Info()
                        self.W, self.H = info.current_w, info.current_h
                        self._screen = pygame.display.set_mode((self.W, self.H), pygame.FULLSCREEN)
                        pygame.mouse.set_visible(False)

        fsm = self.fsm
        state = fsm.state if fsm else State.IDLE
        now = time.monotonic()
        W, H = self.W, self.H

        # Track voice from listener
        if fsm and fsm.voice_listener:
            vtext = fsm.voice_listener.last_text
            if vtext and vtext != self._voice_input:
                self.set_voice_input(vtext)

        # === ANIMATION ===
        self._update_gaze(state, now)
        self._update_blink(now)

        # === RENDER ===
        BG = (12, 14, 20)
        self._screen.fill(BG)

        eye_color = STATE_COLORS.get(state, (120, 140, 200))
        emotion = EMOTION_FROM_STATE.get(state, "neutral")
        STATUS_H = 120

        # === DRAW EYES (top 60% of screen) ===
        eye_area_h = H - STATUS_H
        eye_cy = int(eye_area_h * 0.45)
        eye_spacing = int(W * 0.22)
        left_cx = W // 2 - eye_spacing
        right_cx = W // 2 + eye_spacing

        self._draw_eye(left_cx, eye_cy, eye_color, emotion, W, eye_area_h, is_left=True)
        self._draw_eye(right_cx, eye_cy, eye_color, emotion, W, eye_area_h, is_left=False)

        # === MOUTH (simple expression line) ===
        mouth_y = int(eye_area_h * 0.78)
        mouth_w = int(W * 0.12)
        mouth_cx = W // 2
        mouth_color = tuple(max(0, c - 80) for c in eye_color)

        if emotion == "happy" or state == State.DANCING:
            points = []
            for i in range(21):
                t = i / 20.0
                x = mouth_cx - mouth_w + t * 2 * mouth_w
                y = mouth_y + int(math.sin(t * math.pi) * 25)
                points.append((x, y))
            if len(points) > 1:
                pygame.draw.lines(self._screen, mouth_color, False, points, 4)
        elif emotion == "sad":
            points = []
            for i in range(21):
                t = i / 20.0
                x = mouth_cx - mouth_w + t * 2 * mouth_w
                y = mouth_y - int(math.sin(t * math.pi) * 15)
                points.append((x, y))
            if len(points) > 1:
                pygame.draw.lines(self._screen, mouth_color, False, points, 4)
        elif emotion == "surprised":
            pygame.draw.ellipse(self._screen, mouth_color,
                              (mouth_cx - 20, mouth_y - 15, 40, 30), 3)
        elif emotion == "sleepy":
            pygame.draw.line(self._screen, mouth_color,
                           (mouth_cx - mouth_w // 2, mouth_y),
                           (mouth_cx + mouth_w // 2, mouth_y), 3)
        else:
            pygame.draw.line(self._screen, mouth_color,
                           (mouth_cx - mouth_w, mouth_y),
                           (mouth_cx + mouth_w, mouth_y), 3)

        # === STATUS BAR (bottom) ===
        bar_y = H - STATUS_H
        pygame.draw.rect(self._screen, (20, 22, 30), (0, bar_y, W, STATUS_H))
        pygame.draw.line(self._screen, eye_color, (0, bar_y), (W, bar_y), 2)

        # State name + description (left side)
        st_name = STATE_NAMES.get(state, "?")
        st_desc = STATE_DESCRIPTIONS.get(state, "")
        name_surf = self._fonts['state'].render(st_name, True, eye_color)
        desc_surf = self._fonts['desc'].render(st_desc, True, (140, 145, 165))
        self._screen.blit(name_surf, (30, bar_y + 15))
        self._screen.blit(desc_surf, (30, bar_y + 70))

        # Voice transcript (right side)
        if self._voice_input and now - self._voice_input_time < 8:
            txt = f'"{self._voice_input}"'
            v_surf = self._fonts['voice'].render(txt, True, (0, 200, 255))
            self._screen.blit(v_surf, (W - v_surf.get_width() - 30, bar_y + 15))

            if self._last_intent:
                intent_color = (0, 220, 100) if self._last_confidence > 0.7 else (220, 180, 0)
                i_surf = self._fonts['intent'].render(
                    f"Intent: {self._last_intent} ({self._last_confidence:.0%})", True, intent_color)
                self._screen.blit(i_surf, (W - i_surf.get_width() - 30, bar_y + 55))

        elif self._voice_output and now - self._voice_output_time < 6:
            v_surf = self._fonts['voice'].render(f'"{self._voice_output}"', True, (100, 255, 150))
            self._screen.blit(v_surf, (W - v_surf.get_width() - 30, bar_y + 15))

        # Engine indicator
        engine = "none"
        if fsm and fsm.voice_listener:
            engine = fsm.voice_listener.engine
        engine_surf = self._fonts['xs'].render(f"STT: {engine}", True, (60, 65, 80))
        self._screen.blit(engine_surf, (W - engine_surf.get_width() - 30, bar_y + STATUS_H - 25))

        # Marker info
        if self._detected_markers:
            ids = ", ".join(str(m["id"]) for m in self._detected_markers)
            m_surf = self._fonts['sm'].render(f"Markers: [{ids}]", True, (0, 220, 100))
            self._screen.blit(m_surf, (W // 2 - m_surf.get_width() // 2, bar_y + STATUS_H - 28))

        # === CAMERA PiP (bottom-right corner, above status) ===
        if self._camera_surface:
            pip_x = W - self._camera_surface.get_width() - 15
            pip_y = bar_y - self._camera_surface.get_height() - 15
            border = pygame.Rect(pip_x - 2, pip_y - 2,
                               self._camera_surface.get_width() + 4,
                               self._camera_surface.get_height() + 4)
            pygame.draw.rect(self._screen, eye_color, border, 2, border_radius=6)
            self._screen.blit(self._camera_surface, (pip_x, pip_y))
            cam_label = self._fonts['xs'].render("CAMERA", True, eye_color)
            self._screen.blit(cam_label, (pip_x, pip_y - 20))

        # Dancing: rainbow border effect
        if state == State.DANCING:
            hue = (now * 100) % 360
            import colorsys
            r, g, b = colorsys.hsv_to_rgb(hue / 360, 1.0, 1.0)
            rainbow = (int(r * 255), int(g * 255), int(b * 255))
            pygame.draw.rect(self._screen, rainbow, (0, 0, W, H), 6)

        pygame.display.flip()
        self._clock.tick(30)
        return True

    def _draw_eye(self, cx, cy, color, emotion, screen_w, area_h, is_left=True):
        """Draw a large animated eye."""
        base_w = int(screen_w * 0.14)
        base_h = int(area_h * 0.35)

        # Emotion adjustments
        if emotion == "happy":
            base_h = int(base_h * 0.65)
            cy += int(base_h * 0.15)
        elif emotion == "sad":
            base_h = int(base_h * 0.85)
            cy += int(base_h * 0.08)
        elif emotion == "angry":
            base_h = int(base_h * 0.55)
            cy += int(base_h * 0.2)
        elif emotion == "surprised":
            base_w = int(base_w * 1.15)
            base_h = int(base_h * 1.15)
        elif emotion == "sleepy":
            base_h = int(base_h * 0.3)
            cy += int(area_h * 0.08)
        elif emotion == "love":
            pass
        elif emotion == "confused":
            if not is_left:
                base_h = int(base_h * 0.8)

        # Apply blink
        blink_squeeze = 1.0 - self._blink_state * 0.95
        draw_h = max(4, int(base_h * blink_squeeze))

        # Gaze offset
        gaze_ox = int((self._gaze_x - 0.5) * base_w * 0.3)
        gaze_oy = int((self._gaze_y - 0.5) * draw_h * 0.2)

        # Eye shape
        eye_rect = pygame.Rect(cx - base_w // 2, cy - draw_h // 2, base_w, draw_h)
        roundness = min(base_w // 2, draw_h // 2)

        # Glow effect
        for i in range(3):
            glow_rect = eye_rect.inflate(20 - i * 6, 20 - i * 6)
            glow_color = tuple(max(0, c // (4 - i)) for c in color)
            pygame.draw.rect(self._screen, glow_color, glow_rect, 2, border_radius=roundness + 10 - i * 3)

        pygame.draw.rect(self._screen, color, eye_rect, border_radius=roundness)

        # Pupil
        pupil_r = max(12, min(base_w, draw_h) // 5)
        pupil_cx = cx + gaze_ox
        pupil_cy = cy + gaze_oy
        pygame.draw.circle(self._screen, (12, 14, 20), (pupil_cx, pupil_cy), pupil_r)
        # Pupil highlight
        hl_r = max(4, pupil_r // 3)
        pygame.draw.circle(self._screen, (255, 255, 255),
                          (pupil_cx - pupil_r // 3, pupil_cy - pupil_r // 3), hl_r)

        # Eyebrow
        brow_y = cy - draw_h // 2 - 20
        brow_half = base_w // 2 + 10
        brow_color = tuple(min(255, c + 40) for c in color)
        if emotion == "angry":
            if is_left:
                pygame.draw.line(self._screen, brow_color,
                               (cx - brow_half, brow_y + 20), (cx + brow_half, brow_y - 10), 5)
            else:
                pygame.draw.line(self._screen, brow_color,
                               (cx - brow_half, brow_y - 10), (cx + brow_half, brow_y + 20), 5)
        elif emotion == "sad":
            if is_left:
                pygame.draw.line(self._screen, brow_color,
                               (cx - brow_half, brow_y - 10), (cx + brow_half, brow_y + 15), 4)
            else:
                pygame.draw.line(self._screen, brow_color,
                               (cx - brow_half, brow_y + 15), (cx + brow_half, brow_y - 10), 4)
        elif emotion == "surprised":
            pygame.draw.line(self._screen, brow_color,
                           (cx - brow_half, brow_y - 15), (cx + brow_half, brow_y - 15), 4)
        elif emotion != "sleepy":
            pygame.draw.line(self._screen, brow_color,
                           (cx - brow_half, brow_y), (cx + brow_half, brow_y), 4)

        # Love: draw heart above eye
        if emotion == "love":
            self._draw_heart(cx, cy - draw_h // 2 - 40, 20, color)

    def _draw_heart(self, cx, cy, size, color):
        s = size
        points = [
            (cx, cy + s * 1.2),
            (cx - s, cy),
            (cx - s * 0.6, cy - s),
            (cx, cy - s * 0.4),
            (cx + s * 0.6, cy - s),
            (cx + s, cy),
        ]
        pygame.draw.polygon(self._screen, color, points)

    def _update_gaze(self, state, now):
        """Update eye gaze direction based on state and time."""
        if state == State.ARUCO_SEARCH:
            t = (now * 0.5) % 1.0
            self._target_gaze_x = 0.3 + 0.4 * math.sin(t * math.pi * 2)
            self._target_gaze_y = 0.45
        elif state == State.LISTENING:
            self._target_gaze_x = 0.5
            self._target_gaze_y = 0.5
        elif state == State.DANCING:
            t = now * 2
            self._target_gaze_x = 0.5 + 0.3 * math.sin(t)
            self._target_gaze_y = 0.5 + 0.2 * math.cos(t * 1.3)
        elif state == State.SLEEPING:
            self._target_gaze_x = 0.5
            self._target_gaze_y = 0.6
        else:
            if now - self._idle_gaze_time > 3.0:
                import random
                self._target_gaze_x = 0.3 + random.random() * 0.4
                self._target_gaze_y = 0.4 + random.random() * 0.2
                self._idle_gaze_time = now

        # Smooth interpolation
        lerp = 0.08
        self._gaze_x += (self._target_gaze_x - self._gaze_x) * lerp
        self._gaze_y += (self._target_gaze_y - self._gaze_y) * lerp

    def _update_blink(self, now):
        """Update blink animation."""
        if now - self._last_blink > 4.0:
            self._blink_time = now
            self._last_blink = now

        elapsed = now - self._blink_time if self._blink_time else 999
        if elapsed < 0.12:
            self._blink_state = elapsed / 0.12
        elif elapsed < 0.24:
            self._blink_state = 1.0 - (elapsed - 0.12) / 0.12
        else:
            self._blink_state = 0.0
