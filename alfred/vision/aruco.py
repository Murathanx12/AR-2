"""ArUco marker detection and pose estimation using OpenCV.

Supports both calibrated pose estimation and visual-only (pixel-based) approach
for when camera calibration is not available.
"""

import logging
import math

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _HAS_CV2 = True

    _ARUCO_DICTS = {
        "DICT_4X4_50": cv2.aruco.DICT_4X4_50,
        "DICT_4X4_100": cv2.aruco.DICT_4X4_100,
        "DICT_5X5_50": cv2.aruco.DICT_5X5_50,
        "DICT_6X6_50": cv2.aruco.DICT_6X6_50,
    }
except ImportError:
    _HAS_CV2 = False
    _ARUCO_DICTS = {}


class ArucoDetector:
    """Detects ArUco markers and estimates their pose for navigation.

    Returns marker center, size (pixel), corners for both calibrated
    and visual-only approach modes.
    """

    def __init__(self, dict_name="DICT_4X4_50", marker_size=0.05,
                 camera_matrix=None, dist_coeffs=None):
        """
        Args:
            dict_name: ArUco dictionary name.
            marker_size: Physical marker size in meters (for pose estimation).
            camera_matrix: 3x3 camera intrinsic matrix. If None, pose estimation unavailable.
            dist_coeffs: Distortion coefficients. If None, assumes zero distortion.
        """
        self.dict_name = dict_name
        self.marker_size = marker_size
        self.camera_matrix = camera_matrix
        self.dist_coeffs = dist_coeffs

        self._dictionary = None
        self._parameters = None
        self._detector = None

        if _HAS_CV2:
            dict_id = _ARUCO_DICTS.get(dict_name, cv2.aruco.DICT_4X4_50)
            self._dictionary = cv2.aruco.getPredefinedDictionary(dict_id)
            # Support both old and new OpenCV ArUco API
            if hasattr(cv2.aruco, 'ArucoDetector'):
                # OpenCV 4.7+
                self._parameters = cv2.aruco.DetectorParameters()
                self._detector = cv2.aruco.ArucoDetector(self._dictionary, self._parameters)
            else:
                # OpenCV 4.6 and older
                self._parameters = cv2.aruco.DetectorParameters_create()
                self._detector = None  # use legacy detectMarkers

    def detect(self, frame):
        """Detect ArUco markers in a frame.

        Args:
            frame: BGR image.

        Returns:
            List of dicts with center and size for visual approach:
            [{"id": int, "corners": ndarray(4,2), "center": (cx,cy), "size": float}, ...]
        """
        if not _HAS_CV2 or self._dictionary is None:
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        if self._detector is not None:
            corners, ids, rejected = self._detector.detectMarkers(gray)
        else:
            # Legacy API (OpenCV < 4.7)
            corners, ids, rejected = cv2.aruco.detectMarkers(
                gray, self._dictionary, parameters=self._parameters)

        results = []
        if ids is not None:
            for i, marker_id in enumerate(ids.flatten()):
                pts = corners[i][0]  # shape (4, 2)
                cx = float(np.mean(pts[:, 0]))
                cy = float(np.mean(pts[:, 1]))
                # Approximate size: mean of two adjacent side lengths
                side1 = np.linalg.norm(pts[0] - pts[1])
                side2 = np.linalg.norm(pts[1] - pts[2])
                size = float((side1 + side2) / 2.0)
                results.append({
                    "id": int(marker_id),
                    "corners": pts,
                    "center": (cx, cy),
                    "size": size,
                })
        return results

    def draw_markers(self, frame, markers):
        """Draw detected markers on frame for debug display.

        Args:
            frame: BGR image to draw on (modified in-place).
            markers: List from detect().
        """
        if not _HAS_CV2:
            return
        for m in markers:
            pts = m["corners"].astype(int)
            cv2.polylines(frame, [pts], True, (0, 255, 0), 2)
            cx, cy = int(m["center"][0]), int(m["center"][1])
            cv2.putText(frame, f"ID:{m['id']} sz:{m['size']:.0f}",
                        (cx - 30, cy - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    def estimate_pose(self, marker):
        """Estimate the 6-DOF pose of a detected marker.

        Args:
            marker: Dict with "corners" key from detect().

        Returns:
            Dict with "tvec" and "rvec" as numpy arrays, or None if not calibrated.
        """
        if not _HAS_CV2 or self.camera_matrix is None:
            return None

        dist = self.dist_coeffs if self.dist_coeffs is not None else np.zeros(5)
        corners = marker["corners"].reshape(1, 4, 2)

        rvecs, tvecs, _ = cv2.aruco.estimatePoseSingleMarkers(
            corners, self.marker_size, self.camera_matrix, dist
        )

        return {
            "rvec": rvecs[0][0],
            "tvec": tvecs[0][0],
            "id": marker.get("id"),
        }

    def compute_approach_vector(self, pose):
        """Compute a motion vector (vx, vy, omega) to approach using pose estimation.

        Args:
            pose: Dict from estimate_pose() with "tvec" and "rvec".

        Returns:
            Tuple (vx, vy, omega) as floats, or (0, 0, 0) if pose is None.
        """
        if pose is None:
            return (0.0, 0.0, 0.0)

        tx, ty, tz = pose["tvec"]

        KP_FORWARD = 200.0
        KP_LATERAL = 150.0
        KP_ROTATION = 100.0

        vx = max(0, min(150, KP_FORWARD * tz))
        vy = max(-100, min(100, -KP_LATERAL * tx))
        omega = max(-100, min(100, -KP_ROTATION * math.atan2(tx, tz)))

        return (vx, vy, omega)
