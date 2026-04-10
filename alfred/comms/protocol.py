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


def cmd_spin_left(speed: int) -> str:
    return _format("mv_spinleft", speed)


def cmd_spin_right(speed: int) -> str:
    return _format("mv_spinright", speed)


# --- R5 Indicator commands (NEW) ---

def cmd_led(r: int, g: int, b: int) -> str:
    """Set NeoPixel LED color (all LEDs)."""
    return _format("led", int(r), int(g), int(b))


def cmd_led_pattern(pattern_id: int) -> str:
    """Set LED animation pattern.

    Pattern IDs: 0=off, 1=pulse, 2=rainbow, 3=blink, 4=breathe
    """
    return _format("led_pattern", int(pattern_id))


def cmd_buzzer(freq: int, duration_ms: int) -> str:
    """Play a tone on the buzzer."""
    return _format("buzzer", int(freq), int(duration_ms))
