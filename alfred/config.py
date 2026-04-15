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
    """Ultrasonic sensor (HC-SR04) — R4 obstacle detection."""
    trig_pin: int = 4     # ESP32 GPIO pin for trigger
    echo_pin: int = 2     # ESP32 GPIO pin for echo
    threshold_cm: float = 20.0  # obstacle detection threshold


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
    camera_index: int = 0
    resolution: Tuple[int, int] = (800, 600)
    fps: int = 30
    aruco_dict: str = "DICT_4X4_50"
    aruco_stop_size: int = 150  # pixel size at which marker = "arrived"
    bev_src_points: Tuple[Tuple[int, int], ...] = ()
    bev_dst_points: Tuple[Tuple[int, int], ...] = ()


@dataclass(frozen=True)
class ExpressionConfig:
    """Expression subsystem."""
    oled_address: int = 0x3C
    oled_width: int = 128
    oled_height: int = 64
    neopixel_pin: int = 48    # ESP32 GPIO for NeoPixel data
    neopixel_count: int = 4   # Number of NeoPixel LEDs
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
