"""Camera capture manager using OpenCV."""

import logging
import time
from collections import deque

logger = logging.getLogger(__name__)

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False
    logger.warning("opencv-python not installed — camera unavailable")


class CameraManager:
    """Manages video capture from a camera device via OpenCV."""

    def __init__(self, camera_index=0, resolution=(640, 480), fps=30):
        self.camera_index = camera_index
        self.resolution = resolution
        self.fps = fps
        self._cap = None
        # Rolling timestamps of the last N frames for a live FPS estimate.
        self._frame_times = deque(maxlen=30)
        self._last_fps_log = 0.0

    def open(self):
        """Open the camera device and configure resolution/fps.

        If the configured index fails, auto-scans indices 0-9 to find a working camera.
        """
        if not _HAS_CV2:
            logger.error("Cannot open camera: OpenCV not available")
            return False

        # Try configured index first, then auto-scan
        # Force V4L2 backend to avoid GStreamer issues on Pi
        indices = [self.camera_index] + [i for i in range(10) if i != self.camera_index]
        for idx in indices:
            cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
                cap.set(cv2.CAP_PROP_FPS, self.fps)
                # MJPG is much cheaper to decode than YUYV on USB 2.0, which
                # is what gated us to very low effective FPS at 1080p.
                try:
                    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                    cap.set(cv2.CAP_PROP_FOURCC, fourcc)
                except Exception:
                    pass
                ret, frame = cap.read()
                if ret and frame is not None:
                    self._cap = cap
                    self.camera_index = idx
                    actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    actual_fps = self._cap.get(cv2.CAP_PROP_FPS)
                    logger.info(f"Camera opened on index {idx} at {actual_w}x{actual_h} (driver fps={actual_fps:.0f})")
                    print(f"[Camera] Opened on index {idx} at {actual_w}x{actual_h} (driver fps={actual_fps:.0f})")
                    return True
                cap.release()
            else:
                cap.release()

        print("[Camera] No working camera found (tried indices 0-9)")
        logger.error("No working camera found")
        self._cap = None
        return False

    def read_frame(self):
        """Read a single frame. Returns numpy array or None on failure."""
        if self._cap is None:
            return None
        ret, frame = self._cap.read()
        if not ret:
            return None
        now = time.monotonic()
        self._frame_times.append(now)
        # Log effective FPS every ~5 s so drops are visible in the log without
        # flooding.
        if len(self._frame_times) >= 10 and (now - self._last_fps_log) > 5.0:
            fps = self.actual_fps
            logger.info(f"Camera effective FPS ≈ {fps:.1f} (target {self.fps})")
            self._last_fps_log = now
        return frame

    @property
    def actual_fps(self):
        """Rolling FPS estimate from recent read_frame() calls."""
        if len(self._frame_times) < 2:
            return 0.0
        span = self._frame_times[-1] - self._frame_times[0]
        if span <= 0:
            return 0.0
        return (len(self._frame_times) - 1) / span

    def close(self):
        """Release the camera device."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.info("Camera released")

    @property
    def is_available(self):
        """Whether the camera is currently opened and readable."""
        return self._cap is not None and self._cap.isOpened()
