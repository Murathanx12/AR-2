"""ArUco marker detection and pose estimation using OpenCV."""

import logging
import math

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _HAS_CV2 = True

    # OpenCV 4.7+ uses cv2.aruco.getPredefinedDictionary
    # Older versions use cv2.aruco.Dictionary_get
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
    """Detects ArUco markers and estimates their pose for navigation."""

    def __init__(self, dict_name="DICT_4X4_50", marker_size=0.05, camera_matrix=None, dist_coeffs=None):
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
            self._parameters = cv2.aruco.DetectorParameters()
            self._detector = cv2.aruco.ArucoDetector(self._dictionary, self._parameters)

    def detect(self, frame):
        """Detect ArUco markers in a frame.

        Args:
            frame: BGR image.

        Returns:
            List of dicts: [{"id": int, "corners": ndarray(4,2)}, ...]
        """
        if not _HAS_CV2 or self._detector is None:
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        corners, ids, rejected = self._detector.detectMarkers(gray)

        results = []
        if ids is not None:
            for i, marker_id in enumerate(ids.flatten()):
                results.append({
                    "id": int(marker_id),
                    "corners": corners[i][0],  # shape (4, 2)
                })
        return results

    def estimate_pose(self, marker):
        """Estimate the 6-DOF pose of a detected marker.

        Args:
            marker: Dict with "corners" key from detect().

        Returns:
            Dict with "tvec" (translation) and "rvec" (rotation) as numpy arrays,
            or None if camera not calibrated.
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
        """Compute a motion vector (vx, vy, omega) to approach the marker.

        Uses proportional control on the marker's position relative to camera.

        Args:
            pose: Dict from estimate_pose() with "tvec" and "rvec".

        Returns:
            Tuple (vx, vy, omega) as floats, or (0, 0, 0) if pose is None.
        """
        if pose is None:
            return (0.0, 0.0, 0.0)

        tx, ty, tz = pose["tvec"]

        # Proportional gains
        KP_FORWARD = 200.0   # drive forward proportional to distance
        KP_LATERAL = 150.0   # strafe to centre marker
        KP_ROTATION = 100.0  # rotate to face marker

        # tz = depth (forward distance), tx = lateral offset, ty = vertical offset
        vx = max(0, min(150, KP_FORWARD * tz))  # forward toward marker
        vy = max(-100, min(100, -KP_LATERAL * tx))  # strafe to centre
        omega = max(-100, min(100, -KP_ROTATION * math.atan2(tx, tz)))  # rotate to face

        return (vx, vy, omega)
