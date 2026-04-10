"""ArUco approach controller — drive toward a detected marker.

Supports two modes:
1. Calibrated: Uses pose estimation tvec/rvec for precise distance control.
2. Visual-only: Uses marker pixel size and center for distance/steering
   (like minilab6.py). Works without camera calibration.
"""

import math
import logging

logger = logging.getLogger(__name__)


class ArucoApproach:
    """Drives the robot toward a detected ArUco marker.

    Visual-only mode uses marker pixel size to estimate distance.
    When the marker pixel size exceeds stop_size, the robot has arrived.
    """

    def __init__(self, arrival_distance=0.05,
                 stop_size=150, center_tol_frac=0.10,
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

        Uses marker center for steering and marker pixel size for distance.
        Based on the proven minilab6.py approach logic.

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
        cx, cy = marker["center"]
        size = marker["size"]

        # Close enough — arrived
        if size > self._stop_size:
            return None  # signal arrived

        # Center tolerance
        cx_img = frame_width / 2.0
        error_x = cx - cx_img
        center_tolerance = frame_width * self._center_tol_frac

        # If horizontally off-center, turn first
        if abs(error_x) > center_tolerance:
            # Proportional turn speed
            turn = int(turn_speed * (error_x / (frame_width / 2.0)))
            turn = max(-turn_speed, min(turn_speed, turn))
            return (0, 0, turn)

        # Centered — drive forward. Slow down as marker gets bigger.
        # size ratio: small marker = far away = faster
        size_ratio = min(1.0, size / self._stop_size)
        speed = max(15, int(approach_speed * (1.0 - size_ratio * 0.6)))

        return (speed, 0, 0)

    def is_visual_arrived(self, marker):
        """Check if arrived at marker (visual-only mode).

        Args:
            marker: Dict with "size" key (pixel size).

        Returns:
            True if marker pixel size exceeds stop threshold.
        """
        return marker["size"] > self._stop_size

    @property
    def last_distance(self):
        """Last measured distance to marker, or None."""
        return self._last_distance
