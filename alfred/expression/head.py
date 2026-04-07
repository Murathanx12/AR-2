"""Head controller — servo tilt with animated nod, shake, and person tracking."""

import time
import threading
import logging

logger = logging.getLogger(__name__)

_HAS_SERVO = False
_servo_kit = None

try:
    from adafruit_servokit import ServoKit
    _servo_kit = ServoKit(channels=16)
    _HAS_SERVO = True
except (ImportError, Exception):
    pass


class HeadController:
    """Controls a head-tilt servo for nodding, shaking, and person tracking.

    Falls back to internal angle tracking when hardware is unavailable.
    """

    def __init__(self, channel=0, center=90, range_deg=(45, 135)):
        """
        Args:
            channel: Servo channel on PCA9685.
            center: Center angle in degrees.
            range_deg: (min_angle, max_angle) tuple.
        """
        self._channel = channel
        self._center = center
        self._range_deg = range_deg
        self._angle = center
        self._anim_thread = None
        self._anim_running = False

        self._move_to(center)

    def set_tilt(self, angle):
        """Set head tilt to a specific angle.

        Args:
            angle: Target angle in degrees, clamped to range.
        """
        self._stop_animation()
        self._angle = max(self._range_deg[0], min(self._range_deg[1], angle))
        self._move_to(self._angle)

    def nod(self, amplitude=15, count=2, speed=0.15):
        """Perform a nodding animation (up-down).

        Args:
            amplitude: Degrees of nod movement.
            count: Number of nods.
            speed: Time per half-nod in seconds.
        """
        self._stop_animation()
        self._anim_running = True
        self._anim_thread = threading.Thread(
            target=self._nod_loop, args=(amplitude, count, speed), daemon=True
        )
        self._anim_thread.start()

    def shake(self, amplitude=20, count=2, speed=0.15):
        """Perform a head-shake animation (left-right).

        Note: With a single tilt servo this alternates between tilted positions.
        For a pan servo, this would be lateral movement.

        Args:
            amplitude: Degrees of shake.
            count: Number of shakes.
            speed: Time per half-shake in seconds.
        """
        self._stop_animation()
        self._anim_running = True
        self._anim_thread = threading.Thread(
            target=self._shake_loop, args=(amplitude, count, speed), daemon=True
        )
        self._anim_thread.start()

    def look_at_person(self, face):
        """Adjust head tilt to look at a detected face.

        Args:
            face: Dict with "center" (cx, cy) and optionally "bbox" from PersonDetector.
        """
        if not face or "center" not in face:
            return

        _, cy = face["center"]
        # Map face Y position to servo angle
        # Assuming 480px frame height: top -> tilt up, bottom -> tilt down
        frame_height = face.get("frame_height", 480)
        normalized_y = cy / frame_height  # 0=top, 1=bottom

        # Map to servo range
        target = self._center + (normalized_y - 0.5) * (self._range_deg[1] - self._range_deg[0]) * 0.5
        self.set_tilt(target)

    def center(self):
        """Return head to center position."""
        self.set_tilt(self._center)

    def _move_to(self, angle):
        """Move servo to angle."""
        if _HAS_SERVO and _servo_kit:
            try:
                _servo_kit.servo[self._channel].angle = angle
            except Exception as e:
                logger.debug(f"Servo error: {e}")

    def _stop_animation(self):
        self._anim_running = False
        if self._anim_thread and self._anim_thread.is_alive():
            self._anim_thread.join(timeout=2.0)

    def _nod_loop(self, amplitude, count, speed):
        """Nod animation: up-down from center."""
        for _ in range(count):
            if not self._anim_running:
                break
            # Tilt up
            self._angle = self._center - amplitude
            self._move_to(self._angle)
            time.sleep(speed)
            # Tilt down
            self._angle = self._center + amplitude
            self._move_to(self._angle)
            time.sleep(speed)
        # Return to center
        self._angle = self._center
        self._move_to(self._angle)

    def _shake_loop(self, amplitude, count, speed):
        """Shake animation: alternating tilt from center."""
        for _ in range(count):
            if not self._anim_running:
                break
            self._angle = self._center - amplitude
            self._move_to(self._angle)
            time.sleep(speed)
            self._angle = self._center + amplitude
            self._move_to(self._angle)
            time.sleep(speed)
        self._angle = self._center
        self._move_to(self._angle)

    @property
    def angle(self):
        return self._angle
