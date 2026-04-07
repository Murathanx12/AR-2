"""Bird's-eye view perspective transform and path extraction."""

import logging

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


class BirdEyeView:
    """Transforms camera frames to top-down view and extracts path data."""

    def __init__(self, src_points=None, dst_points=None, output_size=(400, 400)):
        self.output_size = output_size
        self._matrix = None
        self._inv_matrix = None
        if src_points is not None and dst_points is not None:
            self.calibrate(src_points, dst_points)

    def calibrate(self, src_points, dst_points):
        """Compute perspective transform matrices from 4 point correspondences.

        Args:
            src_points: 4 source points as list of (x,y) tuples from camera image.
            dst_points: 4 destination points as list of (x,y) tuples in BEV space.
        """
        if not _HAS_CV2:
            logger.error("OpenCV required for BEV calibration")
            return
        src = np.float32(src_points)
        dst = np.float32(dst_points)
        self._matrix = cv2.getPerspectiveTransform(src, dst)
        self._inv_matrix = cv2.getPerspectiveTransform(dst, src)

    def transform(self, frame):
        """Apply perspective transform to produce a bird's-eye view.

        Args:
            frame: BGR image from camera.

        Returns:
            Warped top-down view image, or None if not calibrated.
        """
        if not _HAS_CV2 or self._matrix is None:
            logger.warning("BEV not calibrated or OpenCV unavailable")
            return None
        return cv2.warpPerspective(frame, self._matrix, self.output_size)

    def inverse_transform(self, bev_frame, original_size):
        """Map BEV image back to camera perspective."""
        if not _HAS_CV2 or self._inv_matrix is None:
            return None
        return cv2.warpPerspective(bev_frame, self._inv_matrix, original_size)

    def extract_path(self, bev):
        """Extract path centreline from a bird's-eye view image.

        Uses adaptive thresholding to find the dark line, then computes
        centroids per row to get the path centre.

        Args:
            bev: Bird's-eye view image (BGR or grayscale).

        Returns:
            List of (x, y) centre points from bottom to top, or empty list.
        """
        if not _HAS_CV2 or bev is None:
            return []

        if len(bev.shape) == 3:
            gray = cv2.cvtColor(bev, cv2.COLOR_BGR2GRAY)
        else:
            gray = bev

        # Adaptive threshold to find dark line on light background
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 25, 10
        )

        # Clean up noise
        kernel = np.ones((3, 3), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

        # Extract centroids per row (sample every 5 rows from bottom to top)
        h, w = binary.shape
        points = []
        for y in range(h - 1, -1, -5):
            row = binary[y, :]
            white_pixels = np.where(row > 0)[0]
            if len(white_pixels) > 0:
                cx = int(np.mean(white_pixels))
                points.append((cx, y))

        return points

    def fit_spline(self, pts, num_points=100):
        """Fit a smooth polynomial through path points.

        Args:
            pts: List of (x, y) points.
            num_points: Number of interpolated output points.

        Returns:
            numpy array of shape (num_points, 2) with smoothed points, or empty array.
        """
        if not _HAS_NP:
            return pts

        if len(pts) < 4:
            return np.array(pts)

        pts = np.array(pts)
        x, y = pts[:, 0], pts[:, 1]

        # Fit polynomial (degree 3 for smooth curves)
        try:
            coeffs = np.polyfit(y, x, min(3, len(pts) - 1))
            poly = np.poly1d(coeffs)
            y_smooth = np.linspace(y.min(), y.max(), num_points)
            x_smooth = poly(y_smooth)
            return np.column_stack([x_smooth, y_smooth])
        except (np.linalg.LinAlgError, ValueError):
            return pts
