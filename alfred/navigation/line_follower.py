"""V3 line-following FSM logic extracted from linefollower.py.

6-state FSM: FOLLOWING, ENDPOINT, LOST_REVERSE, LOST_PIVOT, STOPPED, PARKING.
All constants come from alfred.config.CONFIG.
"""

import time
from enum import IntEnum

from alfred.config import CONFIG
from alfred.comms.protocol import cmd_vector, cmd_stop, cmd_side_pivot


class FollowState(IntEnum):
    FOLLOWING = 0
    ENDPOINT = 1
    LOST_REVERSE = 2
    LOST_PIVOT = 3
    STOPPED = 4
    PARKING = 5


STATE_NAMES = {
    FollowState.FOLLOWING:    "FOLLOW",
    FollowState.ENDPOINT:     "ENDPOINT",
    FollowState.LOST_REVERSE: "LOST_REV",
    FollowState.LOST_PIVOT:   "LOST_PIVOT",
    FollowState.STOPPED:      "STOPPED",
    FollowState.PARKING:      "PARKING",
}

# Sensor indices
IDX_W, IDX_NW, IDX_N, IDX_NE, IDX_E = 0, 1, 2, 3, 4


class LineFollower:
    """V3 algorithmic line follower with 6-state FSM.

    Call tick() at ~30Hz with current IR bits. Returns (vx, vy, omega) command tuple
    and the command string to send over UART.
    """

    def __init__(self, speed: int = None):
        cfg = CONFIG
        self.sensor = cfg.sensor
        self.spd = cfg.speed
        self.curve = cfg.curve
        self.recovery = cfg.recovery
        self.parking = cfg.parking

        self.current_speed = speed or self.spd.default_speed
        self.state = FollowState.FOLLOWING
        self.internal_speed = 0.0
        self.last_turn_var = 0.0
        self.turn_var = 0.0
        self.has_seen_line = False
        self.lost_start_time = None
        self.pseudo_dist = 0.0
        self.last_step_time = 0.0
        self.all_on_start_time = None
        self.parking_start_time = None
        self.finished = False  # set True when parking completes

        # Debug outputs
        self.debug_vx = 0
        self.debug_vy = 0
        self.debug_omega = 0

    def reset(self):
        """Reset FSM to initial FOLLOWING state."""
        self.state = FollowState.FOLLOWING
        self.internal_speed = 0.0
        self.last_step_time = 0.0
        self.has_seen_line = False
        self.lost_start_time = None
        self.pseudo_dist = 0.0
        self.all_on_start_time = None
        self.parking_start_time = None
        self.finished = False

    def _enter_state(self, new_state: FollowState):
        self.state = new_state
        self.pseudo_dist = 0.0

    def _accumulate_pseudo_dist(self, dt: float, speed_fraction: float) -> float:
        self.pseudo_dist += abs(speed_fraction) * dt
        return self.pseudo_dist

    def tick(self, bits: list) -> str:
        """Run one FSM step. Returns the UART command string to send.

        Args:
            bits: List of 5 IR sensor readings [W, NW, N, NE, E], each 0 or 1.

        Returns:
            Command string (e.g. "mv_vector:30,0,15\\n") ready to send.
        """
        now = time.monotonic()
        dt = now - self.last_step_time if self.last_step_time > 0 else 0.0
        self.last_step_time = now

        active_count = sum(bits)
        pattern = ((bits[IDX_E] << 4) | (bits[IDX_NE] << 3) |
                   (bits[IDX_N] << 2) | (bits[IDX_NW] << 1) | bits[IDX_W])

        multiplier = self.current_speed / 5.0

        # -- STATE: STOPPED --
        if self.state == FollowState.STOPPED:
            if self.internal_speed > 0:
                self.internal_speed = max(0.0, self.internal_speed - self.spd.decel * 5)
                vx = int(round(self.internal_speed * multiplier))
                self.debug_vx, self.debug_vy, self.debug_omega = vx, 0, 0
                return cmd_vector(vx, 0, 0)
            else:
                self.debug_vx, self.debug_vy, self.debug_omega = 0, 0, 0
                return cmd_stop()

        # -- STATE: PARKING --
        if self.state == FollowState.PARKING:
            elapsed = time.monotonic() - self.parking_start_time
            if elapsed < self.parking.drive_time:
                self.debug_vx = self.parking.speed
                self.debug_vy, self.debug_omega = 0, 0
                return cmd_vector(self.parking.speed, 0, 0)
            else:
                self.debug_vx, self.debug_vy, self.debug_omega = 0, 0, 0
                self.finished = True
                return cmd_stop()

        # -- STATE: LOST_REVERSE --
        if self.state == FollowState.LOST_REVERSE:
            rev_frac = self.recovery.reverse_speed / self.spd.max_speed
            self._accumulate_pseudo_dist(dt, rev_frac)

            if self.pseudo_dist >= self.recovery.reverse_pseudo_dist_max or active_count > 0:
                self._enter_state(FollowState.LOST_PIVOT)
                return cmd_stop()
            else:
                spd = self.recovery.reverse_speed
                self.debug_vx, self.debug_vy, self.debug_omega = -spd, 0, 0
                return cmd_vector(-spd, 0, 0)

        # -- STATE: LOST_PIVOT --
        if self.state == FollowState.LOST_PIVOT:
            if active_count > 0:
                curr_turn = (sum(b * t for b, t in zip(bits, self.sensor.turn_strengths))
                             / active_count)
                if abs(curr_turn) < 5.0:
                    self._enter_state(FollowState.FOLLOWING)
                    return cmd_stop()

            direction = 1 if self.last_turn_var > 0 else -1
            self.debug_vx, self.debug_vy = 0, 0
            self.debug_omega = direction * self.recovery.pivot_speed
            return cmd_side_pivot(self.recovery.pivot_speed,
                                  self.recovery.pivot_rear_percent, direction)

        # -- STATE: ENDPOINT --
        if self.state == FollowState.ENDPOINT:
            speed_frac = self.internal_speed / 5.0
            self._accumulate_pseudo_dist(dt, speed_frac)

            if active_count == 5:
                if self.all_on_start_time is None:
                    self.all_on_start_time = time.monotonic()
                elapsed_all_on = time.monotonic() - self.all_on_start_time
                if elapsed_all_on >= self.parking.zone_time_threshold:
                    self.state = FollowState.PARKING
                    self.parking_start_time = time.monotonic()
                    self.all_on_start_time = None
                    return cmd_vector(self.parking.speed, 0, 0)

            if self.pseudo_dist >= self.recovery.endpoint_pseudo_dist_max:
                self._enter_state(FollowState.STOPPED)
                self.all_on_start_time = None
                return cmd_stop()

            if 0 < active_count < 5 and pattern not in (0b11011, 0b10001):
                self._enter_state(FollowState.FOLLOWING)
                self.all_on_start_time = None

            if active_count == 0:
                self._enter_state(FollowState.LOST_REVERSE)
                self.all_on_start_time = None
                return cmd_vector(-self.recovery.reverse_speed, 0, 0)

            target_max_speed = self.recovery.endpoint_target_speed
            self.turn_var = 0.0

        # -- STATE: FOLLOWING --
        if self.state == FollowState.FOLLOWING:
            if active_count == 0:
                if self.lost_start_time is None:
                    self.lost_start_time = now
                lost_elapsed = now - self.lost_start_time

                if self.has_seen_line and lost_elapsed >= self.sensor.lost_detection_delay:
                    speed_frac = self.internal_speed / 5.0
                    self._accumulate_pseudo_dist(dt, speed_frac)
                    if self.pseudo_dist >= self.recovery.lost_pseudo_dist_max:
                        self._enter_state(FollowState.LOST_REVERSE)
                        self.internal_speed = 0.0
                        self.lost_start_time = None
                        self.debug_vx, self.debug_vy, self.debug_omega = 0, 0, 0
                        return cmd_stop()

                direction = 1 if self.last_turn_var > 0 else -1
                sweep_omega = direction * self.curve.sweep_turn_speed
                sweep_vx = int(min(self.internal_speed, 1.5) * multiplier * 0.3)
                self.internal_speed = max(0.0, self.internal_speed - self.spd.decel)
                self.debug_vx, self.debug_vy, self.debug_omega = sweep_vx, 0, int(sweep_omega)
                return cmd_vector(sweep_vx, 0, int(sweep_omega))
            else:
                self.pseudo_dist = 0.0
                self.lost_start_time = None
                self.has_seen_line = True

            if active_count == 5:
                self._enter_state(FollowState.ENDPOINT)
                self.all_on_start_time = time.monotonic()
                target_max_speed = self.recovery.endpoint_target_speed
                self.turn_var = 0.0
            else:
                self.turn_var = (sum(b * t for b, t in zip(bits, self.sensor.turn_strengths))
                                 / active_count)
                self.last_turn_var = self.turn_var
                if self.turn_var == 0.0:
                    target_max_speed = 5.0
                else:
                    target_max_speed = (sum(b * m for b, m in zip(bits, self.sensor.move_strengths))
                                        / active_count)

        # -- Shared: smooth speed + rotation --
        if self.internal_speed < target_max_speed:
            self.internal_speed = min(target_max_speed, self.internal_speed + self.spd.accel)
        elif self.internal_speed > target_max_speed:
            self.internal_speed = max(target_max_speed, self.internal_speed - self.spd.decel)

        turn_ratio = min(1.0, abs(self.turn_var) / self.spd.max_turn_strength)

        omega_raw = self.turn_var * self.curve.omega_gain * multiplier / 5.0

        speed_scale = 1.0 - (1.0 - self.curve.curve_slow_factor) * (turn_ratio ** self.curve.curve_slow_expo)
        vx_raw = self.internal_speed * multiplier * speed_scale

        vx = max(-self.spd.max_speed, min(self.spd.max_speed, int(round(vx_raw))))
        omega = max(-self.spd.max_speed, min(self.spd.max_speed, int(round(omega_raw))))

        self.debug_vx, self.debug_vy, self.debug_omega = vx, 0, omega
        return cmd_vector(vx, 0, omega)
