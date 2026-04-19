"""Arm controller — cosmetic servo animations tied to FSM states.

4x SG90 servos on PCA9685 channels 1-4:
  ch1: Left shoulder (perpendicular mount, pans up/down)
  ch2: Left elbow (tilt)
  ch3: Right shoulder
  ch4: Right elbow

All animations are non-blocking (threaded).
"""

import time
import threading
import logging
import math

logger = logging.getLogger(__name__)

_HAS_SERVO = False
_servo_kit = None

try:
    from adafruit_servokit import ServoKit
    _servo_kit = ServoKit(channels=16)
    _HAS_SERVO = True
except (ImportError, Exception):
    pass

# Servo channels
L_SHOULDER = 1
L_ELBOW = 2
R_SHOULDER = 3
R_ELBOW = 4

# Rest positions (degrees)
REST = {L_SHOULDER: 90, L_ELBOW: 90, R_SHOULDER: 90, R_ELBOW: 90}


class ArmController:
    """Controls 4 cosmetic arm servos with state-based animations."""

    def __init__(self):
        self._anim_thread = None
        self._anim_running = False
        self._current_angles = dict(REST)
        self._rest()

    def _move(self, channel, angle):
        angle = max(0, min(180, int(angle)))
        self._current_angles[channel] = angle
        if _HAS_SERVO and _servo_kit:
            try:
                _servo_kit.servo[channel].angle = angle
            except Exception as e:
                logger.debug(f"Arm servo error ch{channel}: {e}")

    def _rest(self):
        for ch, ang in REST.items():
            self._move(ch, ang)

    def _stop_animation(self):
        self._anim_running = False
        if self._anim_thread and self._anim_thread.is_alive():
            self._anim_thread.join(timeout=2.0)

    def _run_anim(self, func, *args):
        self._stop_animation()
        self._anim_running = True
        self._anim_thread = threading.Thread(target=func, args=args, daemon=True)
        self._anim_thread.start()

    def wave(self):
        """Friendly greeting wave with right arm."""
        self._run_anim(self._wave_loop)

    def _wave_loop(self):
        self._move(R_SHOULDER, 150)
        time.sleep(0.3)
        for _ in range(3):
            if not self._anim_running:
                break
            self._move(R_ELBOW, 130)
            time.sleep(0.25)
            self._move(R_ELBOW, 60)
            time.sleep(0.25)
        self._rest()

    def dance(self):
        """Rhythmic arm swinging for dance state."""
        self._run_anim(self._dance_loop)

    def _dance_loop(self):
        t0 = time.monotonic()
        while self._anim_running and time.monotonic() - t0 < 15:
            t = time.monotonic() - t0
            l_sh = 90 + 40 * math.sin(t * 3)
            r_sh = 90 - 40 * math.sin(t * 3)
            l_el = 90 + 30 * math.cos(t * 4)
            r_el = 90 - 30 * math.cos(t * 4)
            self._move(L_SHOULDER, l_sh)
            self._move(R_SHOULDER, r_sh)
            self._move(L_ELBOW, l_el)
            self._move(R_ELBOW, r_el)
            time.sleep(0.05)
        self._rest()

    def point_forward(self):
        """Point both arms forward (searching gesture)."""
        self._run_anim(self._point_loop)

    def _point_loop(self):
        self._move(R_SHOULDER, 160)
        self._move(R_ELBOW, 90)
        while self._anim_running:
            time.sleep(0.1)
        self._rest()

    def carry(self):
        """Arms in carrying/tray position (both forward, elbows bent)."""
        self._run_anim(self._carry_loop)

    def _carry_loop(self):
        self._move(L_SHOULDER, 140)
        self._move(R_SHOULDER, 140)
        self._move(L_ELBOW, 110)
        self._move(R_ELBOW, 110)
        while self._anim_running:
            time.sleep(0.1)
        self._rest()

    def blocked_shrug(self):
        """Shrug gesture when blocked."""
        self._run_anim(self._shrug_loop)

    def _shrug_loop(self):
        self._move(L_SHOULDER, 130)
        self._move(R_SHOULDER, 130)
        self._move(L_ELBOW, 60)
        self._move(R_ELBOW, 60)
        time.sleep(0.5)
        self._move(L_SHOULDER, 90)
        self._move(R_SHOULDER, 90)
        time.sleep(0.3)
        self._move(L_SHOULDER, 130)
        self._move(R_SHOULDER, 130)
        time.sleep(0.5)
        self._rest()

    def sleep_pose(self):
        """Arms down and relaxed for sleep."""
        self._stop_animation()
        self._move(L_SHOULDER, 70)
        self._move(R_SHOULDER, 70)
        self._move(L_ELBOW, 90)
        self._move(R_ELBOW, 90)

    def stop(self):
        """Stop animation and return to rest."""
        self._stop_animation()
        self._rest()

    def express_state(self, state_name):
        """Trigger arm animation based on FSM state name."""
        actions = {
            "IDLE": self.stop,
            "LISTENING": self.stop,
            "FOLLOWING": self.carry,
            "ENDPOINT": self.carry,
            "PARKING": self.carry,
            "ARUCO_SEARCH": self.point_forward,
            "ARUCO_APPROACH": self.point_forward,
            "BLOCKED": self.blocked_shrug,
            "DANCING": self.dance,
            "SLEEPING": self.sleep_pose,
            "PERSON_APPROACH": self.wave,
            "PHOTO": self.wave,
        }
        action = actions.get(state_name)
        if action:
            action()
