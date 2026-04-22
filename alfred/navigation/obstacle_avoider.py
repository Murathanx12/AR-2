"""Obstacle avoider — vector field approach for reactive avoidance.

Uses 3x ultrasonic sensors (left/center/right) as primary distance source,
with camera-based obstacle detection as secondary input.
"""

import math
import logging

logger = logging.getLogger(__name__)


class ObstacleAvoider:
    """Computes avoidance vectors from ultrasonic sensors and camera obstacles.

    Primary: 3x HC-SR04 ultrasonic distances (fast, reliable).
    Secondary: camera-based obstacle list (richer spatial info).
    """

    def __init__(self, repulsion_gain=5000.0, influence_radius=200, max_avoidance=100):
        self._repulsion_gain = repulsion_gain
        self._influence_radius = influence_radius
        self._max_avoidance = max_avoidance
        self._rerouting = False

    def compute_avoidance_ultrasonic(self, distances, threshold_cm=50.0):
        """Compute avoidance from 3 ultrasonic sensor readings.

        Args:
            distances: dict with 'left', 'center', 'right' distance values in cm.
                       -1 means no reading.
            threshold_cm: Distances beyond this are ignored.

        Returns:
            Tuple (vx, vy, omega) avoidance velocity.
        """
        dl = distances.get("left", -1)
        dc = distances.get("center", -1)
        dr = distances.get("right", -1)

        active = {k: v for k, v in [("left", dl), ("center", dc), ("right", dr)]
                  if 0 < v < threshold_cm}

        if not active:
            self._rerouting = False
            return (0, 0, 0)

        self._rerouting = True

        # Repulsive strength: inverse of distance (closer = stronger)
        def strength(d):
            return max(0.0, (1.0 / max(d, 1.0) - 1.0 / threshold_cm)) * threshold_cm

        sl = strength(dl) if dl > 0 else 0.0
        sc = strength(dc) if dc > 0 else 0.0
        sr = strength(dr) if dr > 0 else 0.0

        # Lateral bias: positive = obstacle on left, steer right
        lateral = sl - sr

        # Forward slowdown: based on closest reading
        closest = min(v for v in active.values())
        slowdown = strength(closest)

        vx = int(max(-self._max_avoidance, -slowdown * 15))
        vy = int(max(-self._max_avoidance, min(self._max_avoidance, lateral * 20)))
        omega = int(max(-self._max_avoidance, min(self._max_avoidance, -lateral * 25)))

        return (vx, vy, omega)

    def compute_avoidance(self, obstacles, frame_width=640, frame_height=480):
        """Compute avoidance velocity from camera-detected obstacles.

        Args:
            obstacles: List of obstacle dicts from ObstacleDetector.detect().
                       Each has "center" (cx, cy) and "area" keys.
            frame_width: Camera frame width for normalisation.
            frame_height: Camera frame height for normalisation.

        Returns:
            Tuple (vx, vy, omega) avoidance correction.
        """
        if not obstacles:
            self._rerouting = False
            return (0, 0, 0)

        self._rerouting = True

        robot_x = frame_width / 2
        robot_y = frame_height

        total_fx = 0.0
        total_fy = 0.0

        for obs in obstacles:
            cx, cy = obs["center"]
            dx = robot_x - cx
            dy = robot_y - cy
            dist = math.sqrt(dx * dx + dy * dy)

            if dist < 1:
                dist = 1
            if dist > self._influence_radius:
                continue

            strength = self._repulsion_gain * (1.0 / dist - 1.0 / self._influence_radius)
            area_factor = min(2.0, obs.get("area", 1000) / 1000.0)
            strength *= area_factor

            total_fx += strength * dx / dist
            total_fy += strength * dy / dist

        vx = int(max(-self._max_avoidance, min(0, -total_fy * 0.1)))
        vy = int(max(-self._max_avoidance, min(self._max_avoidance, total_fx * 0.2)))
        omega = int(max(-self._max_avoidance, min(self._max_avoidance, total_fx * 0.3)))

        return (vx, vy, omega)

    def is_rerouting(self):
        """Whether the avoider is currently generating avoidance commands."""
        return self._rerouting
