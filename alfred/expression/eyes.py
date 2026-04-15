"""Eye controller — OLED emotion display with animated gaze tracking."""

import time
import threading
import logging

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

# Try to import OLED hardware
_HAS_OLED = False
_i2c = None
_oled = None

try:
    import board
    import adafruit_ssd1306
    _i2c = board.I2C()
    _HAS_OLED = True
except (ImportError, Exception):
    pass


# Eye shape definitions: each emotion maps to eye drawing parameters
# (left_eye, right_eye) where each is (width, height, y_offset, roundness)
EYE_SHAPES = {
    "neutral":   {"w": 28, "h": 28, "y_off": 0, "round": 14, "brow": 0},
    "happy":     {"w": 30, "h": 20, "y_off": 4, "round": 10, "brow": -3},
    "sad":       {"w": 24, "h": 30, "y_off": 2, "round": 12, "brow": 5},
    "angry":     {"w": 32, "h": 18, "y_off": 4, "round": 6,  "brow": -6},
    "surprised": {"w": 34, "h": 34, "y_off": -2, "round": 17, "brow": -5},
    "sleepy":    {"w": 28, "h": 10, "y_off": 8, "round": 5,  "brow": 0},
    "love":      {"w": 30, "h": 28, "y_off": 0, "round": 14, "brow": -2},
    "confused":  {"w": 26, "h": 26, "y_off": 0, "round": 13, "brow": 3},
}


class EyeController:
    """Controls OLED eye display with emotion and gaze.

    Renders eye shapes to a PIL image. If SSD1306 OLED is connected,
    pushes frames to hardware. Otherwise, maintains internal state for
    GUI rendering.
    """

    EMOTIONS = list(EYE_SHAPES.keys())

    def __init__(self, width=128, height=64, address=0x3C):
        self._width = width
        self._height = height
        self._emotion = "neutral"
        self._x = 0.5  # gaze x: 0=left, 1=right
        self._y = 0.5  # gaze y: 0=up, 1=down
        self._blink_state = 0.0  # 0=open, 1=fully closed
        self._blink_time = time.monotonic()
        self._last_blink = time.monotonic()
        self._auto_blink_interval = 4.0  # seconds between auto blinks
        self._frame = None

        self._oled = None
        if _HAS_OLED:
            try:
                self._oled = adafruit_ssd1306.SSD1306_I2C(width, height, _i2c, addr=address)
                self._oled.fill(0)
                self._oled.show()
                logger.info("OLED display connected")
            except Exception as e:
                logger.warning(f"OLED init failed: {e}")

    def set_emotion(self, emotion):
        """Set the current emotion for eye rendering."""
        if emotion not in self.EMOTIONS:
            raise ValueError(f"Unknown emotion: {emotion}. Use one of: {self.EMOTIONS}")
        self._emotion = emotion

    def look_at(self, x, y):
        """Set gaze direction. x: 0=left to 1=right, y: 0=up to 1=down."""
        self._x = max(0.0, min(1.0, x))
        self._y = max(0.0, min(1.0, y))

    def blink(self):
        """Trigger a blink animation."""
        self._blink_time = time.monotonic()
        self._last_blink = time.monotonic()

    def update(self):
        """Render one frame of eye animation and push to OLED if available."""
        if not _HAS_PIL:
            return

        now = time.monotonic()

        # Auto-blink
        if now - self._last_blink > self._auto_blink_interval:
            self.blink()

        # Blink animation (0.15s close + 0.15s open)
        blink_elapsed = now - self._blink_time if self._blink_time else 999
        if blink_elapsed < 0.15:
            self._blink_state = blink_elapsed / 0.15
        elif blink_elapsed < 0.30:
            self._blink_state = 1.0 - (blink_elapsed - 0.15) / 0.15
        else:
            self._blink_state = 0.0

        # Create image
        img = Image.new('1', (self._width, self._height), 0)
        draw = ImageDraw.Draw(img)

        shape = EYE_SHAPES[self._emotion]
        ew, eh = shape["w"], shape["h"]
        y_off = shape["y_off"]
        brow_off = shape["brow"]

        # Apply blink: squash height
        eh = max(2, int(eh * (1.0 - self._blink_state * 0.9)))

        # Gaze offset (pixels)
        gaze_x = int((self._x - 0.5) * 12)
        gaze_y = int((self._y - 0.5) * 6)

        # Draw both eyes
        cx_left = self._width // 4 + gaze_x
        cx_right = 3 * self._width // 4 + gaze_x
        cy = self._height // 2 + y_off + gaze_y

        for cx in (cx_left, cx_right):
            x0 = cx - ew // 2
            y0 = cy - eh // 2
            x1 = cx + ew // 2
            y1 = cy + eh // 2
            rnd = min(shape["round"], ew // 2, eh // 2)
            draw.rounded_rectangle([x0, y0, x1, y1], radius=rnd, fill=1)

            # Pupil — drawn at eye center (gaze already applied to cx, cy)
            pupil_r = max(2, min(ew, eh) // 6)
            draw.ellipse([cx - pupil_r, cy - pupil_r, cx + pupil_r, cy + pupil_r], fill=0)

            # Eyebrow
            if brow_off != 0:
                brow_y = y0 + brow_off - 4
                draw.line([(x0, brow_y), (x1, brow_y - abs(brow_off))], fill=1, width=2)

        # Love hearts
        if self._emotion == "love":
            for hx in (cx_left, cx_right):
                self._draw_heart(draw, hx, cy - eh // 2 - 6, 5)

        self._frame = img

        # Push to OLED
        if self._oled:
            try:
                self._oled.image(img)
                self._oled.show()
            except Exception:
                pass

    def _draw_heart(self, draw, cx, cy, size):
        """Draw a small heart shape."""
        s = size
        points = [
            (cx, cy + s),
            (cx - s, cy),
            (cx - s//2, cy - s),
            (cx, cy - s//2),
            (cx + s//2, cy - s),
            (cx + s, cy),
        ]
        draw.polygon(points, fill=1)

    def get_frame(self):
        """Return the current eye frame as a PIL Image (for GUI rendering)."""
        return self._frame

    @property
    def emotion(self):
        return self._emotion

    @property
    def gaze(self):
        return (self._x, self._y)
