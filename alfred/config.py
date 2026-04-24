"""Alfred/Sonny V4 configuration — all tunable parameters as frozen dataclasses."""

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass(frozen=True)
class SensorConfig:
    """IR sensor array configuration."""
    reverse_order: bool = False
    lost_detection_delay: float = 1.2  # seconds of no-line before LOST
    turn_strengths: Tuple[float, ...] = (-7.0, -4.5, 0.0, 4.5, 7.0)  # W, NW, N, NE, E
    move_strengths: Tuple[float, ...] = (3.8, 4.2, 5.0, 4.2, 3.8)


@dataclass(frozen=True)
class SpeedConfig:
    """Motor speed limits and acceleration."""
    min_speed: int = 10
    max_speed: int = 150
    default_speed: int = 35
    accel: float = 0.10
    decel: float = 0.07
    max_turn_strength: float = 9.0


@dataclass(frozen=True)
class CurveConfig:
    """Curve handling — slow down + strong rotation."""
    omega_gain: float = 4.5
    sweep_turn_speed: int = 55
    curve_slow_factor: float = 0.20  # at max turn, forward speed = 20%
    curve_slow_expo: float = 1.5     # >1 = stays fast longer on gentle curves


@dataclass(frozen=True)
class RecoveryConfig:
    """Lost-line recovery parameters."""
    reverse_speed: int = 20
    pivot_speed: int = 80
    pivot_rear_percent: int = 15
    endpoint_target_speed: float = 2.0
    reverse_pseudo_dist_max: float = 0.18
    endpoint_pseudo_dist_max: float = 0.4
    lost_pseudo_dist_max: float = 0.35


@dataclass(frozen=True)
class ParkingConfig:
    """Delivery zone parking."""
    zone_time_threshold: float = 0.4
    drive_time: float = 0.8
    speed: int = 15


@dataclass(frozen=True)
class UARTConfig:
    """Serial communication."""
    port: str = '/dev/ttyAMA2'
    baud_rate: int = 115200
    ping_interval: int = 5


@dataclass(frozen=True)
class UltrasonicConfig:
    """HC-SR04 ultrasonic — single centre sensor (TRIG=GPIO8, ECHO=GPIO9)."""
    # Hard emergency: any sustained reading below this triggers BLOCKED.
    # (Overridden by OBSTACLE_THRESHOLD_CM = 30.0 in controller.py — kept
    # here for reference only.)
    threshold_cm: float = 30.0
    # Slow zone for QR-code approach (user spec 2026-04-24 clarified):
    # scale forward speed proportionally below 60 cm. That gives the
    # robot a clean deceleration ramp from 60 cm down to the 30 cm stop
    # so it doesn't overshoot the marker.
    slow_cm: float = 60.0
    slow_debounce: int = 3
    # Universal stop distance: at ≤30 cm we stop. For ArUco approach
    # this is the arrival band (parallels camera STOP_DIST_M=0.30). For
    # a lost marker it means an obstacle — anything below 30 cm when
    # the tag isn't visible is a real blocker, not the marker stand.
    stop_cm: float = 30.0
    stop_debounce: int = 3
    # Reroute trigger: a sustained reading closer than this is treated as
    # a real obstacle in the path — but only when the camera believes the
    # marker is at least `reroute_margin_cm` further away. Otherwise the
    # sensor is just seeing the marker stand and we should keep approaching.
    # 70 cm trigger lets us sidestep obstacles seen well before contact.
    # 20 cm margin keeps the marker stand from false-positiving (camera
    # at 40 + US at 30 → 40 > 30+20 = 50 is false → no spurious reroute).
    reroute_cm: float = 70.0
    reroute_debounce: int = 6
    reroute_margin_cm: float = 20.0
    # Reference only — firmware (esp32/src/main.cpp) is authoritative.
    pins_center: Tuple[int, int] = (8, 9)    # trig, echo


@dataclass(frozen=True)
class VoiceConfig:
    """Voice subsystem."""
    wake_phrase: str = "hello sonny"
    vosk_model: str = "vosk-model-small-en-us-0.15"
    vosk_model_path: str = ""  # auto-detect if empty
    piper_voice: str = "en_US-lessac-medium"
    listen_timeout: float = 5.0
    language: str = "en"  # "en" or "tr"


@dataclass(frozen=True)
class VisionConfig:
    """Vision subsystem."""
    camera_index: int = 1
    resolution: Tuple[int, int] = (1920, 1080)
    fps: int = 30
    aruco_dict: str = "DICT_4X4_50"
    aruco_stop_size: int = 150  # legacy, unused — see ArucoApproach.STOP_DIST_M
    bev_src_points: Tuple[Tuple[int, int], ...] = ()
    bev_dst_points: Tuple[Tuple[int, int], ...] = ()


@dataclass(frozen=True)
class ExpressionConfig:
    """Expression subsystem.

    The robot has no SSD1306 OLED and no NeoPixel LEDs on this build.
    Eyes render to a PIL frame at `eye_width` × `eye_height` and are
    scaled up by the demo/debug Pygame GUI on the 14" HDMI monitor.
    """
    eye_width: int = 128
    eye_height: int = 64
    buzzer_pin: int = 46      # ESP32 GPIO for buzzer
    head_servo_channel: int = 0
    head_center_angle: int = 90
    head_range: Tuple[int, int] = (45, 135)


@dataclass(frozen=True)
class AlfredConfig:
    """Top-level configuration composing all subsystems."""
    sensor: SensorConfig = field(default_factory=SensorConfig)
    speed: SpeedConfig = field(default_factory=SpeedConfig)
    curve: CurveConfig = field(default_factory=CurveConfig)
    recovery: RecoveryConfig = field(default_factory=RecoveryConfig)
    parking: ParkingConfig = field(default_factory=ParkingConfig)
    uart: UARTConfig = field(default_factory=UARTConfig)
    ultrasonic: UltrasonicConfig = field(default_factory=UltrasonicConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    expression: ExpressionConfig = field(default_factory=ExpressionConfig)


# Module-level singleton
CONFIG = AlfredConfig()
