"""Pure command-formatting functions for ESP32 UART protocol.

Each function returns the command string (without encoding).
The UARTBridge is responsible for sending these over serial.
"""


def _format(name: str, *params) -> str:
    param_str = ",".join(str(p) for p in params)
    return f"{name}:{param_str}\n"


def cmd_vector(vx: int, vy: int, omega: int) -> str:
    return _format("mv_vector", int(vx), int(vy), int(omega))


def cmd_stop() -> str:
    return _format("stop", 0)


def cmd_forward(speed: int) -> str:
    return _format("mv_fwd", speed)


def cmd_reverse(speed: int) -> str:
    return _format("mv_rev", speed)


def cmd_strafe_left(speed: int) -> str:
    return _format("mv_left", speed)


def cmd_strafe_right(speed: int) -> str:
    return _format("mv_right", speed)


def cmd_turn_left(speed: int) -> str:
    return _format("mv_turnleft", speed)


def cmd_turn_right(speed: int) -> str:
    return _format("mv_turnright", speed)


def cmd_curve(left_speed: int, right_speed: int) -> str:
    return _format("mv_curve", left_speed, right_speed)


def cmd_side_pivot(front_speed: int, rear_percent: int, direction: int) -> str:
    return _format("mv_sidepivot", front_speed, rear_percent, direction)
