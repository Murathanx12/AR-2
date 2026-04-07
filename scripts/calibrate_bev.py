#!/usr/bin/env python3
"""Bird's-eye-view calibration — select 4 source points for perspective transform."""

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
from alfred.vision.bev import BirdEyeView

points = []

def mouse_callback(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
        points.append((x, y))
        print(f"  Point {len(points)}: ({x}, {y})")


def main():
    print("=== BEV Calibration ===")
    print("Click 4 points on the floor: TL, TR, BR, BL (forming a rectangle)")
    print("The points will be mapped to a 400x400 top-down view.\n")

    cam = CameraManager()
    if not cam.open():
        print("Camera not available.")
        return

    cv2.namedWindow("BEV Calibration")
    cv2.setMouseCallback("BEV Calibration", mouse_callback)

    dst_points = [(0, 0), (400, 0), (400, 400), (0, 400)]
    bev = BirdEyeView()

    while True:
        frame = cam.read_frame()
        if frame is None:
            continue

        display = frame.copy()
        for i, pt in enumerate(points):
            cv2.circle(display, pt, 6, (0, 255, 0), -1)
            cv2.putText(display, str(i + 1), (pt[0] + 10, pt[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        if len(points) >= 2:
            for i in range(len(points) - 1):
                cv2.line(display, points[i], points[i + 1], (0, 255, 0), 1)
        if len(points) == 4:
            cv2.line(display, points[3], points[0], (0, 255, 0), 1)

        cv2.putText(display, f"Points: {len(points)}/4  (R=reset, Q=done)", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.imshow("BEV Calibration", display)

        # Show BEV preview if we have 4 points
        if len(points) == 4:
            bev.calibrate(points, dst_points)
            warped = bev.transform(frame)
            if warped is not None:
                cv2.imshow("BEV Preview", warped)

        key = cv2.waitKey(30) & 0xFF
        if key == ord('r'):
            points.clear()
            print("Points reset.")
        elif key == ord('q') and len(points) == 4:
            break

    cam.close()
    cv2.destroyAllWindows()

    print(f"\nSource points: {points}")
    print(f"Destination points: {dst_points}")
    print("\nAdd to config.py VisionConfig:")
    print(f"  bev_src_points={tuple(points)}")
    print(f"  bev_dst_points={tuple(dst_points)}")


if __name__ == "__main__":
    main()
