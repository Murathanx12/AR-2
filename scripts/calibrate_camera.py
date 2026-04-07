#!/usr/bin/env python3
"""Camera calibration — capture checkerboard images and compute intrinsic matrix."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    import cv2
    import numpy as np
except ImportError:
    print("ERROR: opencv-python and numpy required. pip install opencv-python numpy")
    sys.exit(1)

from alfred.vision.camera import CameraManager


def main():
    print("=== Camera Calibration ===")
    print("Hold a 9x6 checkerboard in front of the camera.")
    print("Press SPACE to capture, Q to finish and compute.\n")

    cam = CameraManager()
    if not cam.open():
        print("Camera not available.")
        return

    board_size = (9, 6)
    square_size = 0.025  # 25mm squares

    obj_points = []
    img_points = []

    objp = np.zeros((board_size[0] * board_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:board_size[0], 0:board_size[1]].T.reshape(-1, 2) * square_size

    count = 0
    while True:
        frame = cam.read_frame()
        if frame is None:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(gray, board_size, None)

        display = frame.copy()
        if found:
            cv2.drawChessboardCorners(display, board_size, corners, found)
            cv2.putText(display, "Board detected! SPACE to capture", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        else:
            cv2.putText(display, "No board found", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        cv2.putText(display, f"Captures: {count}  (need >= 10, Q to finish)", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.imshow("Calibration", display)

        key = cv2.waitKey(30) & 0xFF
        if key == ord(' ') and found:
            refined = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1),
                                       (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
            obj_points.append(objp)
            img_points.append(refined)
            count += 1
            print(f"  Captured frame {count}")
        elif key == ord('q'):
            break

    cam.close()
    cv2.destroyAllWindows()

    if count < 3:
        print(f"Need at least 3 captures (got {count}). Calibration aborted.")
        return

    print(f"\nCalibrating with {count} images...")
    ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(
        obj_points, img_points, gray.shape[::-1], None, None
    )

    print(f"RMS error: {ret:.4f}")
    print(f"\nCamera matrix:\n{mtx}")
    print(f"\nDistortion coefficients:\n{dist}")

    np.savez("camera_calibration.npz", camera_matrix=mtx, dist_coeffs=dist)
    print("\nSaved to camera_calibration.npz")


if __name__ == "__main__":
    main()
