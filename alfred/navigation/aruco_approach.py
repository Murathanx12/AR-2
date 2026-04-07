"""ArUco approach controller — proportional drive toward a detected marker."""

import math
import logging

logger = logging.getLogger(__name__)


class ArucoApproach:
    """Drives the robot toward a detected ArUco marker using proportional control.

    Takes translation/rotation vectors from pose estimation and outputs
    motor commands to centre on and approach the marker.
    """

    def __init__(self, arrival_distance=0.05, kp_forward=200.0, kp_lateral=120.0, kp_rotation=80.0):
        """
        Args:
            arrival_distance: Distance in metres at which we consider "arrived".
            kp_forward: Proportional gain for forward speed.
            kp_lateral: Proportional gain for lateral strafe.
            kp_rotation: Proportional gain for rotation.
        """
        self._arrival_distance = arrival_distance
        self._kp_forward = kp_forward
        self._kp_lateral = kp_lateral
        self._kp_rotation = kp_rotation
        self._last_distance = None

    def compute_approach(self, tvec, rvec):
        """Compute motor command to approach the marker.

        Args:
            tvec: Translation vector [tx, ty, tz] in metres from camera to marker.
                  tx = lateral, ty = vertical, tz = depth (forward distance).
            rvec: Rotation vector (Rodrigues) — used for alignment.

        Returns:
            Tuple (vx, vy, omega) as ints, clipped to [-150, 150].
        """
        tx, ty, tz = tvec[0], tvec[1], tvec[2]
        distance = math.sqrt(tx * tx + tz * tz)
        self._last_distance = distance

        if distance <= self._arrival_distance:
            return (0, 0, 0)

        # Forward: proportional to depth, but reduce as we get close
        vx = self._kp_forward * max(0, tz - self._arrival_distance)
        vx = max(10, min(150, vx))  # minimum creep speed when approaching

        # Lateral: strafe to centre the marker horizontally
        vy = -self._kp_lateral * tx
        vy = max(-100, min(100, vy))

        # Rotation: turn to face the marker
        bearing = math.atan2(tx, tz)
        omega = -self._kp_rotation * bearing
        omega = max(-100, min(100, omega))

        # Slow down as we approach
        slow_factor = min(1.0, distance / (self._arrival_distance * 5))
        vx *= slow_factor

        return (int(vx), int(vy), int(omega))

    def is_arrived(self, tvec):
        """Check if the robot has arrived at the marker.

        Args:
            tvec: Translation vector [tx, ty, tz] in metres.

        Returns:
            True if within arrival_distance of the marker.
        """
        tx, ty, tz = tvec[0], tvec[1], tvec[2]
        distance = math.sqrt(tx * tx + tz * tz)
        self._last_distance = distance
        return distance <= self._arrival_distance

    @property
    def last_distance(self):
        """Last measured distance to marker, or None."""
        return self._last_distance
