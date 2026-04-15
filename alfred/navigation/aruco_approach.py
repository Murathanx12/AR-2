"""ArUco approach controller — drive toward a detected marker.

Supports two modes:
1. Calibrated: Uses pose estimation tvec/rvec for precise distance control.
2. Visual-only: Uses marker pixel size and center for distance/steering
   (like minilab6.py). Works without camera calibration.

Improved: simultaneous steer+drive, smooth speed ramp, temporal filtering.
"""

import math
import time
import logging

logger = logging.getLogger(__name__)


class ArucoApproach:
    """Drives the robot toward a detected ArUco marker.

    Visual-only mode uses marker pixel size to estimate distance.
    When the marker pixel size exceeds stop_size, the robot has arrived.
    Uses simultaneous steering + forward motion for smooth approach.
    """

    def __init__(self, arrival_distance=0.05,
                 stop_size=150, center_tol_frac=0.05,
                 kp_forward=200.0, kp_lateral=120.0, kp_rotation=80.0):
        """
        Args:
            arrival_distance: Distance in metres for calibrated arrival.
            stop_size: Marker pixel size at which visual-only considers "arrived".
            center_tol_frac: Fraction of image width for center tolerance.
            kp_forward: Proportional gain for forward speed (calibrated mode).
            kp_lateral: Proportional gain for lateral strafe (calibrated mode).
            kp_rotation: Proportional gain for rotation (calibrated mode).
        """
        self._arrival_distance = arrival_distance
        self._stop_size = stop_size
        self._center_tol_frac = center_tol_frac
        self._kp_forward = kp_forward
        self._kp_lateral = kp_lateral
        self._kp_rotation = kp_rotation
        self._last_distance = None

        # Temporal smoothing for visual approach
        self._smooth_cx = None
        self._smooth_size = None
        self._alpha = 0.4  # EMA smoothing factor (0=no update, 1=instant)
        self._approach_start_time = None

    # --- Calibrated approach (when camera is calibrated) ---

    def compute_approach(self, tvec, rvec):
        """Compute motor command using calibrated pose estimation.

        Args:
            tvec: Translation vector [tx, ty, tz] in metres.
            rvec: Rotation vector (Rodrigues).

        Returns:
            Tuple (vx, vy, omega) as ints, clipped to [-150, 150].
        """
        tx, ty, tz = tvec[0], tvec[1], tvec[2]
        distance = math.sqrt(tx * tx + tz * tz)
        self._last_distance = distance

        if distance <= self._arrival_distance:
            return (0, 0, 0)

        vx = self._kp_forward * max(0, tz - self._arrival_distance)
        vx = max(10, min(150, vx))

        vy = -self._kp_lateral * tx
        vy = max(-100, min(100, vy))

        bearing = math.atan2(tx, tz)
        omega = -self._kp_rotation * bearing
        omega = max(-100, min(100, omega))

        slow_factor = min(1.0, distance / (self._arrival_distance * 5))
        vx *= slow_factor

        return (int(vx), int(vy), int(omega))

    def is_arrived(self, tvec):
        """Check if arrived at marker (calibrated mode)."""
        tx, ty, tz = tvec[0], tvec[1], tvec[2]
        distance = math.sqrt(tx * tx + tz * tz)
        self._last_distance = distance
        return distance <= self._arrival_distance

    # --- Visual-only approach (no camera calibration needed) ---

    def compute_visual_approach(self, marker, frame_width, frame_height,
                                approach_speed=50, turn_speed=45):
        """Compute motor command using pixel-based marker tracking.

        Uses simultaneous steering + forward motion for smoother approach.
        Applies exponential moving average to reduce jitter from frame noise.

        Args:
            marker: Dict with "center" (cx, cy) and "size" (pixels).
            frame_width: Image width in pixels.
            frame_height: Image height in pixels.
            approach_speed: Forward speed when marker is centered.
            turn_speed: Turn speed when centering marker.

        Returns:
            Tuple (vx, vy, omega) as ints.
            Returns None if arrived (marker size > stop_size).
        """
        raw_cx, raw_cy = marker["center"]
        raw_size = marker["size"]

        # Temporal smoothing (EMA filter)
        if self._smooth_cx is None:
            self._smooth_cx = raw_cx
            self._smooth_size = raw_size
            self._approach_start_time = time.monotonic()
        else:
            self._smooth_cx += self._alpha * (raw_cx - self._smooth_cx)
            self._smooth_size += self._alpha * (raw_size - self._smooth_size)

        cx = self._smooth_cx
        size = self._smooth_size

        # Close enough — arrived
        if size > self._stop_size:
            self._reset_smoothing()
            return None  # signal arrived

        # Compute steering (proportional to horizontal offset)
        cx_img = frame_width / 2.0
        error_x = cx - cx_img
        normalized_error = error_x / (frame_width / 2.0)  # -1 to +1

        omega = int(turn_speed * normalized_error)
        omega = max(-turn_speed, min(turn_speed, omega))

        # Compute forward speed (proportional to distance estimate)
        # Slow down as marker gets bigger (closer)
        size_ratio = min(1.0, size / self._stop_size)

        # Reduce forward speed when steering hard (prevents overshooting)
        steer_factor = 1.0 - 0.5 * abs(normalized_error)
        speed = max(12, int(approach_speed * (1.0 - size_ratio * 0.6) * steer_factor))

        # Very close: creep speed for precise stopping
        if size_ratio > 0.8:
            speed = min(speed, 18)

        return (speed, 0, omega)

    def is_visual_arrived(self, marker):
        """Check if arrived at marker (visual-only mode)."""
        return marker["size"] > self._stop_size

    def _reset_smoothing(self):
        """Reset temporal smoothing state."""
        self._smooth_cx = None
        self._smooth_size = None
        self._approach_start_time = None

    def reset(self):
        """Reset approach state for a new target."""
        self._reset_smoothing()
        self._last_distance = None

    @property
    def last_distance(self):
        """Last measured distance to marker, or None."""
        return self._last_distance
