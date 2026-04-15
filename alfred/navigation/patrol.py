"""Patrol controller — autonomous wandering with person detection."""

import time
import math
import random
import logging

logger = logging.getLogger(__name__)


class PatrolController:
    """Autonomous patrol: random wandering with obstacle avoidance and person approach.

    Generates smooth wander commands that change direction periodically,
    avoid obstacles, and trigger person approach when someone is detected.
    """

    def __init__(self, wander_speed=25, turn_interval=3.0, approach_distance=300):
        """
        Args:
            wander_speed: Base forward speed during patrol.
            turn_interval: Seconds between random direction changes.
            approach_distance: Pixel distance threshold to trigger person approach.
        """
        self.wander_speed = wander_speed
        self.turn_interval = turn_interval
        self.approach_distance = approach_distance

        self._current_omega = 0
        self._last_turn_time = 0.0
        self._target_omega = 0
        self._person_detected = False
        self._person_center = None

    def compute_wander(self, obstacles=None, persons=None):
        """Compute patrol movement command.

        Args:
            obstacles: List of obstacle dicts (from ObstacleDetector), or None.
            persons: List of person/face dicts (from PersonDetector), or None.

        Returns:
            Tuple (vx, vy, omega) for motor control.
        """
        now = time.monotonic()

        # Check for persons
        if persons and len(persons) > 0:
            self._person_detected = True
            # Target the closest (largest) face
            best = max(persons, key=lambda p: p.get("bbox", (0, 0, 0, 0))[2] * p.get("bbox", (0, 0, 0, 0))[3])
            self._person_center = best.get("center")
        else:
            self._person_detected = False
            self._person_center = None

        # Random direction changes at intervals
        if now - self._last_turn_time >= self.turn_interval:
            self._target_omega = random.randint(-40, 40)
            self._last_turn_time = now

        # Smooth omega transition
        self._current_omega += (self._target_omega - self._current_omega) * 0.1

        vx = self.wander_speed
        omega = int(self._current_omega)

        # Obstacle reaction: bias away from obstacles
        if obstacles:
            for obs in obstacles:
                cx, _ = obs.get("center", (400, 300))
                # If obstacle on left half, turn right and vice versa
                if cx < 400:  # approximate center for 800px wide frame
                    omega += 20
                else:
                    omega -= 20
            # Slow down near obstacles
            vx = max(10, vx - len(obstacles) * 5)

        omega = max(-80, min(80, omega))
        return (vx, 0, omega)

    def should_approach_person(self):
        """Whether a person is detected and close enough to approach."""
        return self._person_detected

    def get_person_center(self):
        """Return the pixel center of the detected person, or None."""
        return self._person_center
