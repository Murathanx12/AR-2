"""Path planner — pure pursuit velocity control along a spline."""

import math
import logging

logger = logging.getLogger(__name__)

try:
    import numpy as np
    _HAS_NP = True
except ImportError:
    _HAS_NP = False


class PathPlanner:
    """Converts a path spline + current position into (vx, vy, omega) commands.

    Uses pure pursuit: find a lookahead point on the spline, compute curvature,
    and output velocities that steer toward it.
    """

    def __init__(self, base_speed=30, max_speed=100, k_omega=2.0):
        """
        Args:
            base_speed: Default forward speed.
            max_speed: Maximum motor speed.
            k_omega: Proportional gain for angular velocity.
        """
        self.base_speed = base_speed
        self.max_speed = max_speed
        self.k_omega = k_omega

    def plan_velocities(self, spline, pos, lookahead=0.3):
        """Compute velocity command to follow a spline path.

        Args:
            spline: numpy array of shape (N, 2) — path points (x, y).
            pos: Current robot position as (x, y, theta).
            lookahead: Lookahead distance along the spline (fraction of total length).

        Returns:
            Tuple (vx, vy, omega) as ints, clipped to max_speed.
        """
        if not _HAS_NP or spline is None or len(spline) < 2:
            return (0, 0, 0)

        x, y, theta = pos
        robot_pos = np.array([x, y])

        # Find closest point on spline
        dists = np.linalg.norm(spline - robot_pos, axis=1)
        closest_idx = np.argmin(dists)

        # Find lookahead point
        total_pts = len(spline)
        lookahead_idx = min(total_pts - 1, closest_idx + max(1, int(total_pts * lookahead)))
        target = spline[lookahead_idx]

        # Vector from robot to target
        dx = target[0] - x
        dy = target[1] - y
        dist_to_target = math.sqrt(dx * dx + dy * dy)

        if dist_to_target < 0.01:
            return (0, 0, 0)

        # Target angle
        target_angle = math.atan2(dy, dx)

        # Angle error (normalised to [-pi, pi])
        angle_error = target_angle - theta
        while angle_error > math.pi:
            angle_error -= 2 * math.pi
        while angle_error < -math.pi:
            angle_error += 2 * math.pi

        # Curvature-based speed: slow down on sharp turns
        curvature = abs(angle_error) / max(dist_to_target, 0.01)
        speed_scale = max(0.2, 1.0 - min(1.0, curvature * 2.0))

        vx = int(max(-self.max_speed, min(self.max_speed, self.base_speed * speed_scale)))
        omega = int(max(-self.max_speed, min(self.max_speed, self.k_omega * angle_error * self.base_speed)))

        return (vx, 0, omega)

    def fuse_with_ir(self, planned, ir_correction):
        """Blend planned velocities with IR sensor corrections.

        When IR sensors detect the line drifting, this fuses the vision-planned
        path with the IR-based correction for robust tracking.

        Args:
            planned: Tuple (vx, vy, omega) from plan_velocities.
            ir_correction: Tuple (vx, vy, omega) from line follower.

        Returns:
            Fused (vx, vy, omega) tuple — weighted average favouring IR near the line.
        """
        # IR weight increases when IR correction is strong (close to line)
        ir_strength = abs(ir_correction[2]) / max(abs(planned[2]), 1)
        ir_weight = min(0.8, ir_strength * 0.5)
        vision_weight = 1.0 - ir_weight

        fused = tuple(
            int(vision_weight * p + ir_weight * ir)
            for p, ir in zip(planned, ir_correction)
        )
        return fused
