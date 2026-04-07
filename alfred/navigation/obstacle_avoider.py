"""Obstacle avoider — vector field approach for reactive avoidance."""

import math
import logging

logger = logging.getLogger(__name__)


class ObstacleAvoider:
    """Computes avoidance vectors from detected obstacles.

    Uses a simple repulsive potential field: each obstacle generates a repulsive
    vector inversely proportional to distance. The sum gives the avoidance command.
    """

    def __init__(self, repulsion_gain=5000.0, influence_radius=200, max_avoidance=100):
        """
        Args:
            repulsion_gain: Strength of repulsive force.
            influence_radius: Maximum pixel distance at which obstacles have effect.
            max_avoidance: Maximum avoidance velocity component.
        """
        self._repulsion_gain = repulsion_gain
        self._influence_radius = influence_radius
        self._max_avoidance = max_avoidance
        self._rerouting = False

    def compute_avoidance(self, obstacles, frame_width=640, frame_height=480):
        """Compute avoidance velocity from detected obstacles.

        Args:
            obstacles: List of obstacle dicts from ObstacleDetector.detect().
                       Each has "center" (cx, cy) and "area" keys.
            frame_width: Camera frame width for normalisation.
            frame_height: Camera frame height for normalisation.

        Returns:
            Tuple (vx, vy, omega) avoidance correction to add to planned velocity.
        """
        if not obstacles:
            self._rerouting = False
            return (0, 0, 0)

        self._rerouting = True

        # Robot assumed at bottom-centre of frame
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

            # Repulsive force: stronger when closer
            strength = self._repulsion_gain * (1.0 / dist - 1.0 / self._influence_radius)

            # Scale by obstacle size
            area_factor = min(2.0, obs.get("area", 1000) / 1000.0)
            strength *= area_factor

            # Normalised direction away from obstacle
            total_fx += strength * dx / dist
            total_fy += strength * dy / dist

        # Convert to robot frame: fy (backward=slow down), fx (lateral=strafe/rotate)
        vx = int(max(-self._max_avoidance, min(0, -total_fy * 0.1)))  # slow down
        vy = int(max(-self._max_avoidance, min(self._max_avoidance, total_fx * 0.2)))  # strafe away
        omega = int(max(-self._max_avoidance, min(self._max_avoidance, total_fx * 0.3)))  # rotate away

        return (vx, vy, omega)

    def is_rerouting(self):
        """Whether the avoider is currently generating avoidance commands."""
        return self._rerouting
