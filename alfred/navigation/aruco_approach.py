"""ArUco approach controller — find, center, approach, and hold distance.

Behavior:
1. SEARCH: Rotate slowly scanning for marker
2. CENTER: Stop rotating, turn to face marker directly
3. APPROACH: Drive forward while staying centered
4. HOLD: Maintain distance — if marker moves, follow it

Logs centering errors and distance for debugging.
"""

import math
import time
import logging

logger = logging.getLogger(__name__)

# Import file logger if available
try:
    from alfred.web.app import log_event
except ImportError:
    def log_event(msg): pass


class ArucoApproach:
    """Drives toward an ArUco marker with center-first behavior."""

    # Distance thresholds (in marker pixel size)
    STOP_SIZE = 140        # marker this big = close enough, stop
    HOLD_MIN = 120         # if marker shrinks below this, move closer again
    HOLD_MAX = 160         # if marker grows above this, back up slightly
    CENTER_TOLERANCE = 0.08  # 8% of frame width = "centered"

    def __init__(self):
        self._smooth_cx = None
        self._smooth_size = None
        self._alpha = 0.35  # EMA smoothing
        self._holding = False  # True when maintaining distance

    def compute_visual_approach(self, marker, frame_width, frame_height):
        """Compute motor command to approach marker.

        Logic:
        1. If marker not centered: rotate to center it (no forward motion)
        2. If centered: drive forward, slow down as we get closer
        3. If close enough: stop and hold distance

        Returns:
            Tuple (vx, vy, omega) or None if arrived and holding.
            Also returns state string for logging.
        """
        raw_cx, _ = marker["center"]
        raw_size = marker["size"]

        # Temporal smoothing
        if self._smooth_cx is None:
            self._smooth_cx = raw_cx
            self._smooth_size = raw_size
        else:
            self._smooth_cx += self._alpha * (raw_cx - self._smooth_cx)
            self._smooth_size += self._alpha * (raw_size - self._smooth_size)

        cx = self._smooth_cx
        size = self._smooth_size

        # Center error: -1 (marker on left) to +1 (marker on right)
        cx_img = frame_width / 2.0
        error_x = (cx - cx_img) / (frame_width / 2.0)

        # Log for debugging
        log_event(f"ARUCO: cx_err={error_x:+.2f} size={size:.0f} hold={self._holding}")

        # === HOLD MODE: maintain distance ===
        if self._holding:
            if size < self.HOLD_MIN:
                # Marker moved away — approach again
                self._holding = False
                log_event(f"ARUCO: marker moved away (size={size:.0f}), re-approaching")
            elif size > self.HOLD_MAX:
                # Too close — back up slightly
                omega = int(-20 * error_x)  # stay centered while backing
                log_event(f"ARUCO: too close (size={size:.0f}), backing up")
                return (-15, 0, omega)
            else:
                # Good distance — just stay centered
                if abs(error_x) > self.CENTER_TOLERANCE:
                    omega = int(20 * error_x)
                    return (0, 0, omega)
                return (0, 0, 0)  # perfect — hold still

        # === CENTERING: turn to face marker ===
        if abs(error_x) > self.CENTER_TOLERANCE:
            # Turn to center marker — proportional speed
            omega = int(30 * error_x)
            omega = max(-30, min(30, omega))

            # If very off-center, don't move forward at all
            if abs(error_x) > 0.3:
                log_event(f"ARUCO: centering (err={error_x:+.2f}, omega={omega})")
                return (0, 0, omega)

            # Slightly off — slow forward + steer
            size_ratio = min(1.0, size / self.STOP_SIZE)
            speed = max(10, int(35 * (1.0 - size_ratio * 0.6)))
            return (speed, 0, omega)

        # === APPROACH: centered, drive forward ===
        if size > self.STOP_SIZE:
            # Arrived — enter hold mode
            self._holding = True
            log_event(f"ARUCO: arrived! size={size:.0f}, entering hold mode")
            return (0, 0, 0)

        # Drive forward, speed proportional to distance
        size_ratio = min(1.0, size / self.STOP_SIZE)
        speed = max(12, int(40 * (1.0 - size_ratio * 0.5)))

        # Creep when very close
        if size_ratio > 0.75:
            speed = min(speed, 18)

        log_event(f"ARUCO: approaching (speed={speed}, size_ratio={size_ratio:.2f})")
        return (speed, 0, 0)

    def is_holding(self):
        """Whether we've arrived and are maintaining distance."""
        return self._holding

    def reset(self):
        """Reset for new target."""
        self._smooth_cx = None
        self._smooth_size = None
        self._holding = False
