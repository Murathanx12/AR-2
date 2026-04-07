"""LED controller — NeoPixel state colours and animation effects."""

import time
import threading
import logging
import math

logger = logging.getLogger(__name__)

_HAS_NEOPIXEL = False
_neopixel_mod = None

try:
    import neopixel
    import board
    _HAS_NEOPIXEL = True
    _neopixel_mod = neopixel
except (ImportError, NotImplementedError):
    pass


class LEDController:
    """Controls NeoPixel LED ring for state indication and animations.

    Falls back to internal state tracking when hardware is unavailable.
    """

    STATE_COLORS = {
        "idle":       (0, 0, 50),
        "following":  (0, 100, 0),
        "listening":  (0, 0, 255),
        "error":      (255, 0, 0),
        "dancing":    (255, 0, 255),
        "sleeping":   (10, 10, 10),
        "searching":  (255, 165, 0),
        "approaching":(0, 255, 255),
        "blocked":    (255, 50, 0),
        "parking":    (50, 50, 255),
    }

    def __init__(self, pin=None, count=12, brightness=0.3):
        """
        Args:
            pin: Board pin for NeoPixel data line. None = auto-detect (board.D18).
            count: Number of LEDs in the ring.
            brightness: LED brightness 0.0-1.0.
        """
        self._count = count
        self._brightness = brightness
        self._state = "idle"
        self._pixels = None
        self._anim_thread = None
        self._anim_running = False
        self._current_color = self.STATE_COLORS["idle"]

        if _HAS_NEOPIXEL:
            try:
                hw_pin = pin or board.D18
                self._pixels = _neopixel_mod.NeoPixel(
                    hw_pin, count, brightness=brightness, auto_write=False
                )
                self._set_all(self._current_color)
                logger.info(f"NeoPixel ring initialized: {count} LEDs")
            except Exception as e:
                logger.warning(f"NeoPixel init failed: {e}")

    def set_state(self, state):
        """Set LED state colour immediately.

        Args:
            state: State name (key in STATE_COLORS), or will use idle colour.
        """
        self._stop_animation()
        self._state = state
        self._current_color = self.STATE_COLORS.get(state, self.STATE_COLORS["idle"])
        self._set_all(self._current_color)

    def pulse(self, color, duration=1.0):
        """Pulse LEDs with a color (fade in and out). Non-blocking.

        Args:
            color: RGB tuple (r, g, b).
            duration: Total pulse duration in seconds.
        """
        self._stop_animation()
        self._anim_running = True
        self._anim_thread = threading.Thread(
            target=self._pulse_loop, args=(color, duration), daemon=True
        )
        self._anim_thread.start()

    def rainbow_cycle(self, speed=0.01, duration=5.0):
        """Run a rainbow cycle animation. Non-blocking.

        Args:
            speed: Animation speed (smaller = faster).
            duration: How long to run in seconds.
        """
        self._stop_animation()
        self._anim_running = True
        self._anim_thread = threading.Thread(
            target=self._rainbow_loop, args=(speed, duration), daemon=True
        )
        self._anim_thread.start()

    def off(self):
        """Turn all LEDs off."""
        self._stop_animation()
        self._set_all((0, 0, 0))

    def _set_all(self, color):
        """Set all pixels to one colour."""
        self._current_color = color
        if self._pixels:
            self._pixels.fill(color)
            self._pixels.show()

    def _set_pixel(self, i, color):
        """Set a single pixel."""
        if self._pixels and 0 <= i < self._count:
            self._pixels[i] = color

    def _show(self):
        if self._pixels:
            self._pixels.show()

    def _stop_animation(self):
        self._anim_running = False
        if self._anim_thread and self._anim_thread.is_alive():
            self._anim_thread.join(timeout=1.0)

    def _pulse_loop(self, color, duration):
        """Animate a single pulse."""
        start = time.monotonic()
        while self._anim_running and (time.monotonic() - start) < duration:
            t = (time.monotonic() - start) / duration
            # Sine wave brightness
            brightness = (math.sin(t * math.pi * 2) + 1) / 2
            scaled = tuple(int(c * brightness) for c in color)
            self._set_all(scaled)
            time.sleep(0.03)
        # Restore state colour
        self._set_all(self.STATE_COLORS.get(self._state, (0, 0, 50)))

    def _rainbow_loop(self, speed, duration):
        """Animate rainbow cycle."""
        start = time.monotonic()
        offset = 0
        while self._anim_running and (time.monotonic() - start) < duration:
            for i in range(self._count):
                hue = (i / self._count + offset) % 1.0
                r, g, b = self._hsv_to_rgb(hue, 1.0, 1.0)
                self._set_pixel(i, (r, g, b))
            self._show()
            offset += speed
            time.sleep(0.03)
        self._set_all(self.STATE_COLORS.get(self._state, (0, 0, 50)))

    @staticmethod
    def _hsv_to_rgb(h, s, v):
        """Convert HSV to RGB (0-255)."""
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return int(r * 255), int(g * 255), int(b * 255)

    @property
    def current_color(self):
        return self._current_color

    @property
    def state(self):
        return self._state
