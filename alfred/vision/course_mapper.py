"""Course mapping — accumulate BEV frames to build a track map."""

import logging
import math

logger = logging.getLogger(__name__)

try:
    import numpy as np
    _HAS_NP = True
except ImportError:
    _HAS_NP = False

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False


class CourseMapper:
    """Builds a composite map of the course from BEV frames and robot poses.

    Accumulates BEV frames with associated (x, y, theta) poses, stitches them
    into a single overhead map, and extracts waypoints along the track.
    """

    def __init__(self, map_size=(2000, 2000), scale=5.0):
        """
        Args:
            map_size: Output map size in pixels (width, height).
            scale: Pixels per centimetre.
        """
        self._frames = []
        self._poses = []
        self._map = None
        self._waypoints = []
        self._map_size = map_size
        self._scale = scale
        self._scanning = False

    def start_scan(self):
        """Begin a new course scan, clearing previous data."""
        self._frames = []
        self._poses = []
        self._map = None
        self._waypoints = []
        self._scanning = True
        logger.info("Course scan started")

    def add_frame(self, frame, pose):
        """Add a BEV frame and its associated robot pose.

        Args:
            frame: Bird's-eye view image.
            pose: Tuple (x, y, theta) — robot position in cm and heading in radians.
        """
        if not self._scanning:
            logger.warning("Call start_scan() before adding frames")
            return
        self._frames.append(frame)
        self._poses.append(pose)

    def build_map(self):
        """Stitch collected frames into a composite course map.

        Returns:
            Composite map image, or None if insufficient data.
        """
        if not _HAS_CV2 or not _HAS_NP:
            logger.error("OpenCV and NumPy required for map building")
            return None

        if len(self._frames) < 2:
            logger.warning("Need at least 2 frames to build map")
            return None

        self._scanning = False
        w, h = self._map_size
        cx, cy = w // 2, h // 2

        # Create blank map
        self._map = np.zeros((h, w, 3), dtype=np.uint8)

        for frame, (px, py, theta) in zip(self._frames, self._poses):
            fh, fw = frame.shape[:2]

            # Compute placement: rotate frame by theta, translate to (px, py)
            cos_t, sin_t = math.cos(theta), math.sin(theta)

            # Build affine transform: rotate + translate
            M = np.float32([
                [cos_t, -sin_t, cx + px * self._scale - fw / 2],
                [sin_t,  cos_t, cy + py * self._scale - fh / 2],
            ])

            warped = cv2.warpAffine(frame, M, (w, h))

            # Blend: non-zero pixels overwrite
            mask = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY) > 10
            self._map[mask] = warped[mask]

        self._extract_waypoints()
        logger.info(f"Map built: {len(self._frames)} frames, {len(self._waypoints)} waypoints")
        return self._map

    def _extract_waypoints(self):
        """Extract waypoints from the composite map by finding the track centreline."""
        if self._map is None:
            return

        gray = cv2.cvtColor(self._map, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 30, 255, cv2.THRESH_BINARY)

        # Find contours of the track
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return

        # Take largest contour as the track
        track = max(contours, key=cv2.contourArea)

        # Sample points along the contour as waypoints
        epsilon = 0.01 * cv2.arcLength(track, True)
        approx = cv2.approxPolyDP(track, epsilon, True)

        cx, cy = self._map_size[0] // 2, self._map_size[1] // 2
        self._waypoints = []
        for pt in approx:
            px = (pt[0][0] - cx) / self._scale
            py = (pt[0][1] - cy) / self._scale
            self._waypoints.append((px, py))

    def get_waypoints(self):
        """Return waypoints extracted from the map.

        Returns:
            List of (x, y) tuples in centimetre coordinates.
        """
        return list(self._waypoints)

    def get_map_image(self):
        """Return the composite map image, or None if not built yet."""
        return self._map
