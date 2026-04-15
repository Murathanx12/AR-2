"""Thread-safe UART bridge for ESP32 communication.

Reads IR_STATUS and DIST (ultrasonic) messages from ESP32.
Sends motor, LED, and buzzer commands to ESP32.
"""

import threading
import time
import logging

logger = logging.getLogger(__name__)

try:
    import serial
    _HAS_SERIAL = True
except ImportError:
    _HAS_SERIAL = False
    serial = None
    logger.warning("pyserial not installed — UART unavailable")

from alfred.config import CONFIG
from alfred.comms.protocol import cmd_stop


class UARTBridge:
    """Manages serial connection to ESP32 with daemon reader thread."""

    def __init__(self, port: str = None, baud_rate: int = None):
        cfg = CONFIG.uart
        self._port = port or cfg.port
        self._baud_rate = baud_rate or cfg.baud_rate
        self._ser = None
        self._ir_status = 0
        self._ir_lock = threading.Lock()
        self._distance_cm = -1.0  # ultrasonic distance, -1 = no reading
        self._dist_lock = threading.Lock()
        self._running = False
        self._thread = None
        self._ping_interval = cfg.ping_interval

    def open(self):
        """Open serial port and start reader thread."""
        if not _HAS_SERIAL:
            print("[UART] WARNING: pyserial not installed. Motors will NOT work.")
            return
        try:
            self._ser = serial.Serial(self._port, self._baud_rate, timeout=1)
            self._running = True
            self._thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._thread.start()
            print(f"[UART] Connected to ESP32 on {self._port} @ {self._baud_rate}")
        except (OSError, serial.SerialException) as e:
            print(f"[UART] FAILED to open {self._port}: {e}")
            print(f"[UART] Motors will NOT work. Check:")
            print(f"[UART]   1. ESP32 is powered on (12V battery)")
            print(f"[UART]   2. UART wires: Pi TX(pin8) -> ESP32 RX(GPIO16)")
            print(f"[UART]   3. UART wires: Pi RX(pin10) -> ESP32 TX(GPIO17)")
            print(f"[UART]   4. GND connected between Pi and ESP32")
            print(f"[UART]   5. Run: ls -la /dev/ttyAMA2")

    def close(self):
        """Stop reader thread and close serial port."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self.send(cmd_stop())
        if self._ser and self._ser.is_open:
            self._ser.close()

    def send(self, command: str):
        """Send a pre-formatted command string over serial."""
        if self._ser and self._ser.is_open:
            self._ser.write(command.encode())
        elif command.strip() not in ("stop:0",):
            # Log dropped commands (except frequent stop) so user knows UART is down
            logger.debug(f"[UART] Dropped (no connection): {command.strip()}")

    def get_ir_status(self) -> int:
        """Return raw 5-bit IR status word (thread-safe)."""
        with self._ir_lock:
            return self._ir_status

    def get_ir_bits(self, reverse: bool = None) -> list:
        """Return list of 5 IR sensor booleans [W, NW, N, NE, E].

        Args:
            reverse: Override sensor order reversal. Defaults to config value.
        """
        if reverse is None:
            reverse = CONFIG.sensor.reverse_order
        v = self.get_ir_status()
        if reverse:
            return [(v >> (4 - i)) & 1 for i in range(5)]
        return [(v >> i) & 1 for i in range(5)]

    def get_distance(self) -> float:
        """Return latest ultrasonic distance in cm, or -1 if no reading."""
        with self._dist_lock:
            return self._distance_cm

    def is_obstacle_detected(self, threshold_cm: float = 20.0) -> bool:
        """Check if an obstacle is within threshold distance.

        Args:
            threshold_cm: Distance threshold in cm.

        Returns:
            True if obstacle detected closer than threshold.
        """
        dist = self.get_distance()
        return 0 < dist < threshold_cm

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def _reader_loop(self):
        """Daemon thread: read IR_STATUS and DIST lines, send periodic pings."""
        last_ping = time.monotonic()
        while self._running:
            try:
                line = self._ser.readline()
                text = line.decode(errors='ignore').strip()
                if text:
                    if text.startswith("IR_STATUS:"):
                        try:
                            _, value_str = text.split(":", 1)
                            with self._ir_lock:
                                self._ir_status = int(value_str) & 0x1F
                        except ValueError:
                            pass
                    elif text.startswith("DIST:"):
                        try:
                            _, value_str = text.split(":", 1)
                            dist = float(value_str)
                            with self._dist_lock:
                                self._distance_cm = dist
                        except ValueError:
                            pass

                now = time.monotonic()
                if now - last_ping >= self._ping_interval:
                    self._ser.write(b"hello from pi\n")
                    last_ping = now
            except (OSError, Exception) as e:
                print(f"[UART] Connection lost: {e}")
                break
        print("[UART] Reader thread stopped")
