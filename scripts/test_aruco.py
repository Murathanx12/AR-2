#!/usr/bin/env python3
"""ArUco detection test — open camera and display detected markers with pose."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    import cv2
    import numpy as np
except ImportError:
    print("ERROR: opencv-python and numpy required.")
    sys.exit(1)

from alfred.vision.camera import CameraManager
from alfred.vision.aruco import ArucoDetector


def main():
    print("=== ArUco Detection Test ===")
    print("Press Q to quit.\n")

    cam = CameraManager()
    if not cam.open():
        print("Camera not available.")
        return

    # Load calibration if available
    camera_matrix = None
    dist_coeffs = None
    if os.path.exists("camera_calibration.npz"):
        data = np.load("camera_calibration.npz")
        camera_matrix = data["camera_matrix"]
        dist_coeffs = data["dist_coeffs"]
        print("Loaded camera calibration.")

    detector = ArucoDetector(
        camera_matrix=camera_matrix,
        dist_coeffs=dist_coeffs,
    )

    while True:
        frame = cam.read_frame()
        if frame is None:
            continue

        markers = detector.detect(frame)

        for m in markers:
            corners = m["corners"].astype(int)
            cv2.polylines(frame, [corners], True, (0, 255, 0), 2)
            cv2.putText(frame, f"ID:{m['id']}", tuple(corners[0]),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

            pose = detector.estimate_pose(m)
            if pose:
                tvec = pose["tvec"]
                cv2.putText(frame, f"d={np.linalg.norm(tvec):.3f}m",
                            (corners[0][0], corners[0][1] + 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1)

        cv2.putText(frame, f"Markers: {len(markers)}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.imshow("ArUco Test", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cam.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
