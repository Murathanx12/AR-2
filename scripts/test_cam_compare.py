#!/usr/bin/env python3
"""Back-to-back camera comparison: 1080p vs 720p.

Uses raw MJPG, no scaling, no post-processing. Measures:
  - Actual delivered resolution and aspect ratio
  - Effective FPS (camera side, after driver buffers)
  - ArUco marker detection reliability
  - Marker pixel-size at each resolution (for FOV comparison)

Keep the 18 cm marker at the SAME physical position for both runs
(e.g. 30 cm in front of the camera). Then the size ratio tells us
whether 720p crops the FOV: expected size_720 / size_1080 ≈ 1280/1920
= 0.667 if there's no crop.

Run: python3 scripts/test_cam_compare.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    import cv2
except ImportError:
    print("ERROR: opencv not installed")
    sys.exit(1)

from alfred.vision.aruco import ArucoDetector
from alfred.navigation.aruco_approach import ArucoApproach


def open_camera_raw(index, w, h, fps_req):
    """Open camera with MJPG raw, no post-processing."""
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None
    # MJPG is the sensor-native wire format — zero decode work beyond JPEG.
    # Set FOURCC BEFORE resolution; some drivers need this order to honour MJPG.
    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
    cap.set(cv2.CAP_PROP_FOURCC, fourcc)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    cap.set(cv2.CAP_PROP_FPS, fps_req)
    # Disable OpenCV's RGB auto-conversion surprises — we want raw decode only.
    try:
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 1)   # still need BGR to run detector
    except Exception:
        pass
    # Shrink the internal V4L2 buffer so we always read the newest frame
    # rather than a stale one.
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    return cap


def run_test(cap, label, seconds, detector, approach):
    print(f"\n=== {label} ===")
    aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    drv_fps = cap.get(cv2.CAP_PROP_FPS)
    fourcc_i = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc_s = "".join(chr((fourcc_i >> (8*i)) & 0xFF) for i in range(4))
    print(f"Actual      : {aw}x{ah}  aspect={aw/ah:.3f}  driver_fps={drv_fps:.0f}  fourcc={fourcc_s}")

    # drain any pre-buffered frames before timing
    for _ in range(5):
        cap.read()

    t0 = time.monotonic()
    frames = 0
    with_marker = 0
    sizes = []
    mean_brightness = []
    last_print = 0.0
    while time.monotonic() - t0 < seconds:
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        frames += 1
        markers = detector.detect(frame)
        # Sample brightness on every 10th frame — cheap diagnostic
        if frames % 10 == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            mean_brightness.append(float(gray.mean()))
        if markers:
            m = max(markers, key=lambda x: x["size"])
            sizes.append(m["size"])
            with_marker += 1
            now = time.monotonic()
            if now - last_print >= 0.4:
                d = approach._distance_m(m["size"], aw)
                print(f"  t={now-t0:5.1f}  id={m['id']:3d}  size={m['size']:6.1f}px  "
                      f"dist={d:.3f} m  frames={frames}")
                last_print = now

    elapsed = time.monotonic() - t0
    fps = frames / elapsed if elapsed > 0 else 0
    print(f"Result      : {frames} frames in {elapsed:.1f}s -> {fps:.1f} fps, "
          f"{with_marker} with marker ({100*with_marker/max(frames,1):.0f}%)")
    if sizes:
        sizes.sort()
        med = sizes[len(sizes)//2]
        print(f"Pixel size  : median={med:.1f}  min={sizes[0]:.1f}  max={sizes[-1]:.1f}")
    else:
        med = None
    if mean_brightness:
        mb = sum(mean_brightness)/len(mean_brightness)
        print(f"Brightness  : mean={mb:.0f}/255 (low = sensor starving for light)")
    return {"w": aw, "h": ah, "fps": fps, "median_size": med,
            "with_marker": with_marker, "frames": frames}


def main():
    detector = ArucoDetector()
    approach = ArucoApproach()

    print("Back-to-back 1080p / 720p test — keep the marker at 30 cm, steady.")
    print("If FOV is identical (no crop), 720p size should be ~0.667 of 1080p.")

    # 1080p baseline
    cap = open_camera_raw(0, 1920, 1080, 30)
    if cap is None:
        print("ERROR: no camera")
        return 1
    r1080 = run_test(cap, "1080p @ req 30 fps MJPG raw", 10, detector, approach)
    cap.release()
    time.sleep(0.5)

    # 720p — request 30 fps even though v4l2 only lists 60; driver may honour it,
    # which lets the sensor use longer exposure (better WDR in low light).
    cap = open_camera_raw(0, 1280, 720, 30)
    if cap is None:
        print("ERROR: camera re-open failed")
        return 1
    r720_30 = run_test(cap, "720p @ req 30 fps MJPG raw", 10, detector, approach)
    cap.release()
    time.sleep(0.5)

    # 720p at 60 for completeness (forces shorter exposure)
    cap = open_camera_raw(0, 1280, 720, 60)
    if cap is None:
        print("ERROR: camera re-open failed")
        return 1
    r720_60 = run_test(cap, "720p @ req 60 fps MJPG raw", 10, detector, approach)
    cap.release()

    # FOV analysis
    print("\n=== FOV crop check ===")
    if r1080["median_size"] and r720_30["median_size"]:
        expected = r1080["median_size"] * 1280/1920
        observed = r720_30["median_size"]
        ratio = observed / expected
        print(f"720p size expected if no crop: {expected:.1f} px")
        print(f"720p size observed           : {observed:.1f} px  (ratio {ratio:.2f}x)")
        if 0.94 <= ratio <= 1.06:
            print("FOV preserved — no crop at 720p. ✓")
        else:
            print("FOV differs — 720p is cropped or scaled differently.")
    else:
        print("(Not enough detections to compare.)")

    print("\nSummary:")
    for r, label in [(r1080, "1080p@30"), (r720_30, "720p@30-req"), (r720_60, "720p@60-req")]:
        print(f"  {label:15s} fps={r['fps']:5.1f}  "
              f"detect={r['with_marker']}/{r['frames']}  "
              f"size={r['median_size']}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
