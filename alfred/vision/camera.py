"""Camera capture manager using OpenCV."""

import logging

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

    def open(self):
        """Open the camera device and configure resolution/fps."""
        if not _HAS_CV2:
            logger.error("Cannot open camera: OpenCV not available")
            return False
        self._cap = cv2.VideoCapture(self.camera_index)
        if not self._cap.isOpened():
            logger.error(f"Failed to open camera index {self.camera_index}")
            self._cap = None
            return False
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        self._cap.set(cv2.CAP_PROP_FPS, self.fps)
        logger.info(f"Camera {self.camera_index} opened at {self.resolution}")
        return True

    def read_frame(self):
        """Read a single frame. Returns numpy array or None on failure."""
        if self._cap is None:
            return None
        ret, frame = self._cap.read()
        if not ret:
            return None
        return frame

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
