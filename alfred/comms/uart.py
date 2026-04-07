"""Thread-safe UART bridge for ESP32 communication.

Extracted from linefollower.py uart_thread() and serial init.
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
        self._running = False
        self._thread = None
        self._ping_interval = cfg.ping_interval

    def open(self):
        """Open serial port and start reader thread."""
        if not _HAS_SERIAL:
            logger.warning("UART unavailable (pyserial not installed). Running in dry-run mode.")
            return
        try:
            self._ser = serial.Serial(self._port, self._baud_rate, timeout=1)
            self._running = True
            self._thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._thread.start()
        except (OSError, serial.SerialException) as e:
            logger.warning(f"UART open failed: {e}. Running in dry-run mode.")

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

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def _reader_loop(self):
        """Daemon thread: read IR_STATUS lines and send periodic pings."""
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

                now = time.monotonic()
                if now - last_ping >= self._ping_interval:
                    self._ser.write(b"hello from pi\n")
                    last_ping = now
            except (OSError, Exception):
                break
