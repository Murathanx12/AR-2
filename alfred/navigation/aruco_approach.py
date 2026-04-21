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
    """Drives toward an ArUco marker with center-first behavior.

    Distance is computed from marker pixel size using the pinhole model:
        distance_m = (physical_marker_m * focal_length_px) / pixel_size
    focal_length_px is approximated from frame width (≈0.8·width) — good
    enough for a ~20 cm stop target on typical USB webcams. Using real
    distance instead of raw pixel size keeps thresholds resolution-independent;
    the old pixel-based thresholds (STOP_SIZE=140) caused the robot to enter
    hold-mode and back up for any marker visible at 1920×1080.
    """

    # Physical geometry of the printed ArUco marker. Adjust to match whatever
    # marker size you're actually using.
    PHYSICAL_MARKER_M = 0.05     # 5 cm tag
    FOCAL_RATIO = 0.8            # focal_px ≈ 0.8 · frame_width

    # Target stop distance ≈ 20 cm with a small dead band so the robot doesn't
    # oscillate forward/back around the set point. Ultrasonic will refine this
    # once wired up.
    STOP_DIST_M = 0.20
    HOLD_NEAR_M = 0.15           # closer than this → back up
    HOLD_FAR_M  = 0.30           # farther than this while holding → nudge forward
    APPROACH_REENGAGE_M = 0.35   # drifted past this → leave hold, re-approach

    CENTER_TOLERANCE = 0.08      # 8 % of frame width = "centered"

    def __init__(self):
        self._smooth_cx = None
        self._smooth_size = None
        self._alpha = 0.35  # EMA smoothing
        self._holding = False  # True when maintaining distance

    def _distance_m(self, pixel_size, frame_width):
        if pixel_size <= 0:
            return float("inf")
        focal_px = self.FOCAL_RATIO * frame_width
        return (self.PHYSICAL_MARKER_M * focal_px) / pixel_size

    def _forward_speed(self, dist_m):
        """Ramp: fast when far, creep through the final 10 cm."""
        if dist_m > 1.0:
            return 40
        if dist_m > 0.5:
            return 30
        if dist_m > 0.30:
            return 20
        return 14

    def compute_visual_approach(self, marker, frame_width, frame_height):
        """Compute motor command to approach marker.

        Logic:
        1. If marker not centered: rotate to center it (no forward motion)
        2. If centered: drive forward, slow down as we get closer
        3. If within STOP_DIST_M: stop and hold distance
        Returns (vx, vy, omega). vx > 0 = forward, vx < 0 = reverse.
        """
        raw_cx, _ = marker["center"]
        raw_size = marker["size"]

        if self._smooth_cx is None:
            self._smooth_cx = raw_cx
            self._smooth_size = raw_size
        else:
            self._smooth_cx += self._alpha * (raw_cx - self._smooth_cx)
            self._smooth_size += self._alpha * (raw_size - self._smooth_size)

        cx = self._smooth_cx
        size = self._smooth_size

        cx_img = frame_width / 2.0
        error_x = (cx - cx_img) / (frame_width / 2.0)

        dist_m = self._distance_m(size, frame_width)
        log_event(f"ARUCO: cx_err={error_x:+.2f} size={size:.0f}px dist={dist_m:.2f}m hold={self._holding}")

        # === HOLD MODE: maintain distance ===
        if self._holding:
            if dist_m > self.APPROACH_REENGAGE_M:
                self._holding = False
                log_event(f"ARUCO: marker moved away (dist={dist_m:.2f}m), re-approaching")
            elif dist_m < self.HOLD_NEAR_M:
                # While backing up we still want the camera (facing forward)
                # to track the marker: if marker is to the right we spin
                # right (omega > 0), same convention line-follower uses.
                omega = int(20 * error_x)
                log_event(f"ARUCO: too close (dist={dist_m:.2f}m), backing up")
                return (-15, 0, omega)
            elif dist_m > self.HOLD_FAR_M:
                omega = int(15 * error_x)
                log_event(f"ARUCO: drifted out (dist={dist_m:.2f}m), nudging forward")
                return (10, 0, omega)
            else:
                if abs(error_x) > self.CENTER_TOLERANCE:
                    omega = int(20 * error_x)
                    return (0, 0, omega)
                return (0, 0, 0)

        # === CENTERING: turn to face marker ===
        if abs(error_x) > self.CENTER_TOLERANCE:
            omega = int(30 * error_x)
            omega = max(-30, min(30, omega))

            if abs(error_x) > 0.3:
                log_event(f"ARUCO: centering (err={error_x:+.2f}, omega={omega})")
                return (0, 0, omega)

            speed = self._forward_speed(dist_m)
            return (speed, 0, omega)

        # === APPROACH: centered, drive forward ===
        if dist_m <= self.STOP_DIST_M:
            self._holding = True
            log_event(f"ARUCO: arrived! dist={dist_m:.2f}m, entering hold mode")
            return (0, 0, 0)

        speed = self._forward_speed(dist_m)
        log_event(f"ARUCO: approaching (speed={speed}, dist={dist_m:.2f}m)")
        return (speed, 0, 0)

    def is_holding(self):
        """Whether we've arrived and are maintaining distance."""
        return self._holding

    def reset(self):
        """Reset for new target."""
        self._smooth_cx = None
        self._smooth_size = None
        self._holding = False
