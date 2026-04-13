"""Alfred V4 debug GUI — Pygame-based dashboard for monitoring and control.

Enhanced from V3 linefollower GUI with camera feed, voice status, and 17-state FSM display.
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

from alfred.fsm.states import State, STATE_NAMES


# State colour map for the 17 FSM states
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


class DebugGUI:
    """Pygame-based debug GUI for monitoring Alfred/Sonny.

    Displays sensor state, vector field, FSM status, camera feed,
    voice status, and provides keyboard control.
    """

    def __init__(self, fsm=None, width=900, height=620):
        """
        Args:
            fsm: AlfredFSM instance for reading state.
            width: Window width.
            height: Window height.
        """
        if not _HAS_PYGAME:
            raise RuntimeError("pygame is required for GUI")

        self.fsm = fsm
        self.W = width
        self.H = height
        self._running = False
        self._screen = None
        self._clock = None
        self._fonts = {}

        # Manual control state
        self._pressed = {'w': False, 's': False, 'a': False, 'd': False, 'q': False, 'e': False}
        self._manual_mode = True  # start in manual

        # Animated values for smooth transitions
        self._anim_vx = 0.0
        self._anim_vy = 0.0
        self._anim_omega = 0.0

        # Camera frame surface
        self._camera_surface = None

    def start(self):
        """Initialize pygame and open the window."""
        pygame.init()
        self._screen = pygame.display.set_mode((self.W, self.H))
        pygame.display.set_caption("Sonny V4 — Alfred Debug GUI")
        self._clock = pygame.time.Clock()
        self._fonts = {
            'lg': pygame.font.SysFont(None, 32),
            'md': pygame.font.SysFont(None, 26),
            'sm': pygame.font.SysFont(None, 22),
            'xs': pygame.font.SysFont(None, 18),
        }
        self._running = True
        logger.info("Debug GUI started")

    def stop(self):
        """Close the GUI."""
        self._running = False
        if _HAS_PYGAME and pygame.get_init():
            pygame.quit()
        logger.info("Debug GUI stopped")

    def is_running(self):
        return self._running

    def set_camera_frame(self, frame):
        """Update the camera preview panel with a new frame.

        Args:
            frame: BGR numpy array from OpenCV, or None.
        """
        if frame is None or not _HAS_PYGAME:
            self._camera_surface = None
            return
        try:
            import cv2
            # Resize for panel
            small = cv2.resize(frame, (200, 150))
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            self._camera_surface = pygame.surfarray.make_surface(rgb.swapaxes(0, 1))
        except Exception:
            self._camera_surface = None

    def update(self):
        """Process events and render one frame. Call at ~60Hz.

        Returns:
            False if the user closed the window, True otherwise.
        """
        if not self._running or not _HAS_PYGAME:
            return False

        # -- Event handling --
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
                return False
            elif event.type == pygame.KEYDOWN:
                self._handle_keydown(event.key)
            elif event.type == pygame.KEYUP:
                self._handle_keyup(event.key)

        # -- Get FSM data --
        fsm = self.fsm
        state = fsm.state if fsm else State.IDLE
        lf = fsm.line_follower if fsm else None
        uart = fsm.uart if fsm else None

        bits = [0, 0, 0, 0, 0]
        if uart and uart.is_open:
            bits = uart.get_ir_bits()

        debug_vx = lf.debug_vx if lf else 0
        debug_vy = lf.debug_vy if lf else 0
        debug_omega = lf.debug_omega if lf else 0
        internal_speed = lf.internal_speed if lf else 0.0
        pseudo_dist = lf.pseudo_dist if lf else 0.0
        current_speed = lf.current_speed if lf else 35
        turn_var = lf.turn_var if lf else 0.0

        active = sum(bits)
        turn_display = (sum(b * t for b, t in zip(bits, (-7, -4.5, 0, 4.5, 7))) / active) if active > 0 else 0.0

        # Smooth animation
        lerp = 0.25
        self._anim_vx += (debug_vx - self._anim_vx) * lerp
        self._anim_vy += (debug_vy - self._anim_vy) * lerp
        self._anim_omega += (debug_omega - self._anim_omega) * lerp

        max_speed = 150

        # -- Render --
        self._screen.fill((16, 18, 24))

        LEFT_W = 360
        RIGHT_X = 375

        # === HEADER BAR ===
        pygame.draw.rect(self._screen, (32, 36, 46), (0, 0, self.W, 48))
        pygame.draw.line(self._screen, (50, 55, 70), (0, 48), (self.W, 48))
        self._screen.blit(self._fonts['lg'].render("SONNY", True, (70, 160, 255)), (18, 12))

        # Mode pill
        mode_label = "AUTO" if not self._manual_mode else "MANUAL"
        mode_color = (0, 220, 100) if not self._manual_mode else (220, 180, 0)
        pill_text = self._fonts['md'].render(mode_label, True, mode_color)
        pill_w = pill_text.get_width() + 24
        pill_rect = pygame.Rect(120, 10, pill_w, 28)
        pygame.draw.rect(self._screen, mode_color, pill_rect, 1, border_radius=14)
        self._screen.blit(pill_text, (132, 13))

        # State pill
        state_name = STATE_NAMES.get(state, '?')
        st_color = STATE_COLORS.get(state, (180, 180, 180))
        st_text = self._fonts['md'].render(state_name, True, st_color)
        st_w = st_text.get_width() + 24
        st_rect = pygame.Rect(self.W - st_w - 16, 10, st_w, 28)
        pygame.draw.rect(self._screen, st_color, st_rect, 1, border_radius=14)
        self._screen.blit(st_text, (self.W - st_w - 4, 13))

        # Voice indicator
        voice_active = fsm and fsm.voice_listener is not None
        voice_color = (0, 180, 255) if voice_active else (60, 60, 70)
        voice_label = "MIC ON" if voice_active else "MIC OFF"
        self._screen.blit(self._fonts['xs'].render(voice_label, True, voice_color), (pill_rect.right + 20, 18))

        y = 58

        # === LEFT COLUMN: Sensors, Turn bar, Stats ===

        # -- Sensor arc --
        panel_h = 100
        pygame.draw.rect(self._screen, (26, 30, 38), (10, y, LEFT_W, panel_h), border_radius=10)
        pygame.draw.rect(self._screen, (40, 45, 58), (10, y, LEFT_W, panel_h), 1, border_radius=10)
        self._screen.blit(self._fonts['xs'].render("IR SENSORS", True, (80, 85, 100)), (20, y + 6))

        sensor_names = ['W', 'NW', 'N', 'NE', 'E']
        arc_positions = [(55, 62), (115, 34), (180, 22), (245, 34), (305, 62)]
        for i, (sx, sy) in enumerate(arc_positions):
            on = bits[i]
            cx, cy = sx, y + sy
            if on:
                glow = pygame.Surface((48, 48), pygame.SRCALPHA)
                pygame.draw.circle(glow, (0, 200, 60, 40), (24, 24), 22)
                self._screen.blit(glow, (cx - 24, cy - 18))
            box_color = (0, 200, 60) if on else (42, 46, 56)
            border_color = (0, 255, 80) if on else (55, 60, 72)
            pygame.draw.rect(self._screen, box_color, (cx - 24, cy - 13, 48, 28), border_radius=6)
            pygame.draw.rect(self._screen, border_color, (cx - 24, cy - 13, 48, 28), 1, border_radius=6)
            lbl = self._fonts['sm'].render(sensor_names[i], True, (255, 255, 255) if on else (90, 90, 100))
            self._screen.blit(lbl, (cx - lbl.get_width() // 2, cy - 7))
        y += panel_h + 8

        # -- Turn indicator bar --
        bar_h = 38
        pygame.draw.rect(self._screen, (26, 30, 38), (10, y, LEFT_W, bar_h), border_radius=8)
        pygame.draw.rect(self._screen, (40, 45, 58), (10, y, LEFT_W, bar_h), 1, border_radius=8)
        bar_cx = 10 + LEFT_W // 2
        bar_w = 240
        pygame.draw.rect(self._screen, (42, 46, 56), (bar_cx - bar_w // 2, y + 15, bar_w, 8), border_radius=4)
        pygame.draw.rect(self._screen, (80, 85, 100), (bar_cx - 1, y + 10, 2, 18))
        self._screen.blit(self._fonts['xs'].render("L", True, (80, 85, 100)), (bar_cx - bar_w // 2 - 14, y + 12))
        self._screen.blit(self._fonts['xs'].render("R", True, (80, 85, 100)), (bar_cx + bar_w // 2 + 5, y + 12))

        norm_turn = max(-1.0, min(1.0, turn_display / 7.0))
        dot_x = bar_cx + int(norm_turn * bar_w // 2)
        dot_color = (255, 70, 70) if abs(norm_turn) > 0.6 else (255, 190, 50) if abs(norm_turn) > 0.3 else (60, 210, 110)
        pygame.draw.circle(self._screen, dot_color, (dot_x, y + 19), 8)
        self._screen.blit(self._fonts['xs'].render(f"{turn_display:+.1f}", True, (140, 150, 170)), (18, y + 10))
        y += bar_h + 8

        # -- Stats cards --
        card_h = 60
        cards = [
            ("SPEED", f"{current_speed}", (100, 180, 255)),
            ("ALGO", f"{internal_speed:.1f}", (180, 220, 130)),
            ("DIST", f"{pseudo_dist:.2f}", (220, 180, 80)),
        ]
        card_w = (LEFT_W - 16) // 3
        for ci, (label, value, color) in enumerate(cards):
            cx = 10 + ci * (card_w + 4)
            pygame.draw.rect(self._screen, (26, 30, 38), (cx, y, card_w, card_h), border_radius=8)
            pygame.draw.rect(self._screen, (40, 45, 58), (cx, y, card_w, card_h), 1, border_radius=8)
            self._screen.blit(self._fonts['xs'].render(label, True, (80, 85, 100)), (cx + 10, y + 8))
            self._screen.blit(self._fonts['md'].render(value, True, color), (cx + 10, y + 28))
        y += card_h + 8

        # -- Vector readout --
        vec_h = 42
        pygame.draw.rect(self._screen, (26, 30, 38), (10, y, LEFT_W, vec_h), border_radius=8)
        pygame.draw.rect(self._screen, (40, 45, 58), (10, y, LEFT_W, vec_h), 1, border_radius=8)
        self._screen.blit(self._fonts['xs'].render("OUTPUT", True, (80, 85, 100)), (20, y + 4))
        vxc = (100, 220, 130) if debug_vx > 0 else (220, 100, 100) if debug_vx < 0 else (110, 110, 120)
        vyc = (100, 180, 255) if debug_vy != 0 else (110, 110, 120)
        omc = (220, 170, 60) if debug_omega != 0 else (110, 110, 120)
        self._screen.blit(self._fonts['sm'].render(f"vx:{debug_vx:+d}", True, vxc), (20, y + 20))
        self._screen.blit(self._fonts['sm'].render(f"vy:{debug_vy:+d}", True, vyc), (130, y + 20))
        self._screen.blit(self._fonts['sm'].render(f"\u03c9:{debug_omega:+d}", True, omc), (240, y + 20))
        y += vec_h + 8

        # === RIGHT COLUMN: Vector viz + Throttle + Camera ===
        viz_w = self.W - RIGHT_X - 12
        viz_h = 220
        viz_cx = RIGHT_X + viz_w // 2
        viz_cy = 58 + viz_h // 2
        viz_r = min(viz_w, viz_h) // 2 - 16

        # Vector field panel
        pygame.draw.rect(self._screen, (26, 30, 38), (RIGHT_X, 58, viz_w, viz_h), border_radius=10)
        pygame.draw.rect(self._screen, (40, 45, 58), (RIGHT_X, 58, viz_w, viz_h), 1, border_radius=10)
        self._screen.blit(self._fonts['xs'].render("VECTOR FIELD", True, (80, 85, 100)), (RIGHT_X + 10, 62))

        # Grid circles
        for r_frac in [0.33, 0.66, 1.0]:
            r = int(viz_r * r_frac)
            pygame.draw.circle(self._screen, (34, 38, 48), (viz_cx, viz_cy), r, 1)
        pygame.draw.line(self._screen, (34, 38, 48), (viz_cx - viz_r, viz_cy), (viz_cx + viz_r, viz_cy))
        pygame.draw.line(self._screen, (34, 38, 48), (viz_cx, viz_cy - viz_r), (viz_cx, viz_cy + viz_r))

        # Direction labels
        self._screen.blit(self._fonts['xs'].render("FWD", True, (55, 60, 75)), (viz_cx - 10, viz_cy - viz_r - 14))
        self._screen.blit(self._fonts['xs'].render("REV", True, (55, 60, 75)), (viz_cx - 10, viz_cy + viz_r + 3))
        self._screen.blit(self._fonts['xs'].render("L", True, (55, 60, 75)), (viz_cx - viz_r - 10, viz_cy - 6))
        self._screen.blit(self._fonts['xs'].render("R", True, (55, 60, 75)), (viz_cx + viz_r + 4, viz_cy - 6))

        # Robot body
        bot = 14
        pygame.draw.rect(self._screen, (55, 60, 75), (viz_cx - bot, viz_cy - bot, bot * 2, bot * 2), border_radius=4)
        pygame.draw.rect(self._screen, (75, 82, 100), (viz_cx - bot, viz_cy - bot, bot * 2, bot * 2), 1, border_radius=4)
        pygame.draw.rect(self._screen, (100, 180, 255), (viz_cx - 4, viz_cy - bot - 4, 8, 5), border_radius=2)

        # Vector arrow
        arrow_scale = viz_r / max_speed
        ax = self._anim_vy * arrow_scale
        ay = -self._anim_vx * arrow_scale
        arrow_len = math.sqrt(ax * ax + ay * ay)
        if arrow_len > 3:
            if self._anim_vx > 0:
                arrow_color = (80, 220, 130)
            elif self._anim_vx < -3:
                arrow_color = (220, 80, 80)
            else:
                arrow_color = (80, 160, 255)
            self._draw_arrow(self._screen, arrow_color, (viz_cx, viz_cy),
                           (viz_cx + int(ax), viz_cy + int(ay)), width=3, head_size=11)

        # Rotation arc
        if abs(self._anim_omega) > 3:
            arc_r = bot + 10
            arc_color = (220, 170, 60)
            arc_start = -0.5 if self._anim_omega > 0 else 2.6
            arc_span = min(abs(self._anim_omega) / max_speed * 3.14, 2.8)
            steps = max(8, int(arc_span * 12))
            points = []
            for s in range(steps + 1):
                a = arc_start + (arc_span * s / steps) * (1 if self._anim_omega > 0 else -1)
                points.append((viz_cx + int(arc_r * math.cos(a)),
                               viz_cy + int(arc_r * math.sin(a))))
            if len(points) > 1:
                pygame.draw.lines(self._screen, arc_color, False, points, 2)
                if len(points) >= 2:
                    self._draw_arrow(self._screen, arc_color, points[-2], points[-1], width=2, head_size=7)

        # Throttle gauge
        gauge_y = 58 + viz_h + 10
        gauge_h = 50
        pygame.draw.rect(self._screen, (26, 30, 38), (RIGHT_X, gauge_y, viz_w, gauge_h), border_radius=8)
        pygame.draw.rect(self._screen, (40, 45, 58), (RIGHT_X, gauge_y, viz_w, gauge_h), 1, border_radius=8)
        self._screen.blit(self._fonts['xs'].render("THROTTLE", True, (80, 85, 100)), (RIGHT_X + 10, gauge_y + 6))

        gauge_bar_w = viz_w - 24
        gauge_fill = max(0.0, min(1.0, internal_speed / 5.0))
        pygame.draw.rect(self._screen, (42, 46, 56), (RIGHT_X + 12, gauge_y + 24, gauge_bar_w, 12), border_radius=6)
        fill_color = (220, 70, 70) if gauge_fill > 0.8 else (220, 180, 50) if gauge_fill > 0.5 else (60, 200, 120)
        if gauge_fill > 0.01:
            pygame.draw.rect(self._screen, fill_color, (RIGHT_X + 12, gauge_y + 24, int(gauge_bar_w * gauge_fill), 12), border_radius=6)
        pct_label = f"{gauge_fill * 100:.0f}%"
        self._screen.blit(self._fonts['sm'].render(pct_label, True, fill_color), (RIGHT_X + gauge_bar_w - 20, gauge_y + 38))

        # Camera feed panel
        cam_y = gauge_y + gauge_h + 10
        cam_h = 160
        pygame.draw.rect(self._screen, (26, 30, 38), (RIGHT_X, cam_y, viz_w, cam_h), border_radius=10)
        pygame.draw.rect(self._screen, (40, 45, 58), (RIGHT_X, cam_y, viz_w, cam_h), 1, border_radius=10)
        self._screen.blit(self._fonts['xs'].render("CAMERA", True, (80, 85, 100)), (RIGHT_X + 10, cam_y + 4))

        if self._camera_surface:
            self._screen.blit(self._camera_surface, (RIGHT_X + (viz_w - 200) // 2, cam_y + 8))
        else:
            no_cam = self._fonts['sm'].render("No feed", True, (60, 60, 70))
            self._screen.blit(no_cam, (RIGHT_X + viz_w // 2 - no_cam.get_width() // 2, cam_y + cam_h // 2 - 8))

        # === KEY HELP (bottom) ===
        help_y = self.H - 52
        pygame.draw.rect(self._screen, (26, 30, 38), (10, help_y, self.W - 20, 42), border_radius=8)
        help_color = (70, 75, 90)
        self._screen.blit(self._fonts['xs'].render(
            "W/S fwd/rev  A/D strafe  Q/E rotate  M auto  1/2 speed  SPACE stop  F follow  ESC quit",
            True, help_color), (22, help_y + 6))
        self._screen.blit(self._fonts['xs'].render(
            "All keys combinable for omnidirectional movement  |  V4 Sonny",
            True, (55, 60, 75)), (22, help_y + 24))

        pygame.display.flip()
        self._clock.tick(60)
        return True

    def _handle_keydown(self, key):
        """Handle key press events."""
        from alfred.comms.protocol import cmd_vector, cmd_stop

        fsm = self.fsm
        lf = fsm.line_follower if fsm else None

        if key == pygame.K_m:
            self._manual_mode = not self._manual_mode
            self._pressed = {k: False for k in self._pressed}
            if fsm:
                if self._manual_mode:
                    fsm.transition(State.IDLE)
                    fsm.uart.send(cmd_stop())
                else:
                    fsm.transition(State.FOLLOWING)
                    if lf:
                        lf.reset()
        elif key == pygame.K_f:
            # Quick follow shortcut
            if fsm:
                self._manual_mode = False
                fsm.transition(State.FOLLOWING)
                if lf:
                    lf.reset()
        elif key == pygame.K_SPACE:
            self._pressed = {k: False for k in self._pressed}
            if fsm:
                fsm.uart.send(cmd_stop())
                fsm.transition(State.IDLE)
            self._manual_mode = True
        elif key == pygame.K_ESCAPE:
            self._running = False
        elif key == pygame.K_1:
            if lf:
                lf.current_speed = max(10, lf.current_speed - 5)
            self._update_manual_movement()
        elif key == pygame.K_2:
            if lf:
                lf.current_speed = min(150, lf.current_speed + 5)
            self._update_manual_movement()
        elif key in (pygame.K_w, pygame.K_s, pygame.K_a, pygame.K_d, pygame.K_q, pygame.K_e):
            key_map = {pygame.K_w: 'w', pygame.K_s: 's', pygame.K_a: 'a',
                       pygame.K_d: 'd', pygame.K_q: 'q', pygame.K_e: 'e'}
            self._pressed[key_map[key]] = True
            self._update_manual_movement()

    def _handle_keyup(self, key):
        """Handle key release events."""
        key_map = {pygame.K_w: 'w', pygame.K_s: 's', pygame.K_a: 'a',
                   pygame.K_d: 'd', pygame.K_q: 'q', pygame.K_e: 'e'}
        if key in key_map:
            self._pressed[key_map[key]] = False
            self._update_manual_movement()

    def _update_manual_movement(self):
        """Send manual movement commands based on pressed keys."""
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
        """Draw an arrow from start to end."""
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
