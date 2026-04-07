"""Obstacle detection using contour analysis."""

import logging

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False


class ObstacleDetector:
    """Detects obstacles in camera frames using contour analysis.

    Assumes obstacles are dark/colored objects on a lighter floor.
    """

    def __init__(self, min_area=500, roi_fraction=0.6):
        """
        Args:
            min_area: Minimum contour area in pixels to count as obstacle.
            roi_fraction: Bottom fraction of frame to analyze (ignore sky/walls).
        """
        self.min_area = min_area
        self.roi_fraction = roi_fraction

    def detect(self, frame):
        """Detect obstacles in a frame.

        Args:
            frame: BGR image.

        Returns:
            List of dicts: [{"bbox": (x,y,w,h), "area": int, "center": (cx,cy)}, ...]
        """
        if not _HAS_CV2 or frame is None:
            return []

        h, w = frame.shape[:2]
        roi_y = int(h * (1.0 - self.roi_fraction))
        roi = frame[roi_y:, :]

        # Convert to HSV and threshold for obstacles (non-floor regions)
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        # Detect dark objects (shadows, obstacles)
        lower_dark = np.array([0, 0, 0])
        upper_dark = np.array([180, 255, 80])
        mask = cv2.inRange(hsv, lower_dark, upper_dark)

        # Clean up
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        obstacles = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self.min_area:
                continue
            x, y, bw, bh = cv2.boundingRect(cnt)
            cx = x + bw // 2
            cy = y + bh // 2 + roi_y  # offset back to full frame coords
            obstacles.append({
                "bbox": (x, y + roi_y, bw, bh),
                "area": int(area),
                "center": (cx, cy),
            })

        return sorted(obstacles, key=lambda o: o["area"], reverse=True)

    def is_path_clear(self, frame):
        """Check if the path ahead is clear of obstacles.

        Analyzes the centre strip of the bottom portion of the frame.

        Args:
            frame: BGR image.

        Returns:
            True if no significant obstacles in the forward path.
        """
        if not _HAS_CV2 or frame is None:
            return True

        obstacles = self.detect(frame)
        if not obstacles:
            return True

        h, w = frame.shape[:2]
        center_margin = w // 4
        center_left = w // 2 - center_margin
        center_right = w // 2 + center_margin

        for obs in obstacles:
            cx, _ = obs["center"]
            if center_left <= cx <= center_right:
                return False

        return True
