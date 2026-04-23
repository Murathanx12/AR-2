#!/usr/bin/env python3
"""Headless ArUco distance + FPS test.

Uses the same pinhole model as ArucoApproach. Lets you verify the
camera is delivering the requested resolution (full 16:9 FOV, no crop)
and the effective FPS under live detection load.

  python3 scripts/test_aruco_distance.py                 # default: 1920x1080 @ 30 fps
  python3 scripts/test_aruco_distance.py --res 1280x720  # try 720p @ 60 fps
  python3 scripts/test_aruco_distance.py --res 1920x1080 --fps 30
  python3 scripts/test_aruco_distance.py --seconds 15    # stop automatically

Ctrl-C to quit. Prints a 5 Hz distance log plus a summary of effective
FPS and ArUco pixel size.
"""

import argparse
import signal
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from alfred.vision.camera import CameraManager
from alfred.vision.aruco import ArucoDetector
from alfred.navigation.aruco_approach import ArucoApproach


_running = True


def _stop(*_):
    global _running
    _running = False


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--res", default="1920x1080",
                   help="Capture resolution WxH (default 1920x1080, try 1280x720)")
    p.add_argument("--fps", type=int, default=30, help="Requested FPS (camera may cap)")
    p.add_argument("--seconds", type=float, default=0.0,
                   help="Auto-stop after N seconds (0 = run until Ctrl-C)")
    p.add_argument("--index", type=int, default=0, help="Camera index")
    return p.parse_args()


def main():
    args = parse_args()
    try:
        rw, rh = (int(x) for x in args.res.lower().split("x"))
    except ValueError:
        print(f"Bad --res '{args.res}'; use format WxH (e.g. 1920x1080)")
        return 2

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    approach = ArucoApproach()
    print("=== ArUco Distance + FPS Test ===")
    print(f"Requested    : {rw}x{rh} @ {args.fps} fps")
    print(f"Marker size  : {approach.PHYSICAL_MARKER_M*100:.1f} cm")
    print(f"FOCAL_RATIO  : {approach.FOCAL_RATIO}")
    print(f"Stop / Hold  : {approach.STOP_DIST_M*100:.0f} cm target, "
          f"{approach.HOLD_NEAR_M*100:.0f}–{approach.HOLD_FAR_M*100:.0f} cm hold band")
    print()

    cam = CameraManager(camera_index=args.index, resolution=(rw, rh), fps=args.fps)
    if not cam.open():
        print("ERROR: camera not available.")
        return 1

    detector = ArucoDetector()

    print("Hold the 18 cm ArUco marker steady at your target distance.")
    print("Columns: t=sec  id=id  cx=px  size=px  dist=m  fps=live  (zone)")
    print("-" * 78)

    t0 = time.monotonic()
    last_print = 0.0
    frames_seen = 0
    frames_with_marker = 0
    frame_w_obs = None
    frame_h_obs = None
    pixel_sizes = []  # for calibration summary

    while _running:
        frame = cam.read_frame()
        if frame is None:
            time.sleep(0.01)
            continue
        frames_seen += 1
        h, w = frame.shape[:2]
        frame_w_obs, frame_h_obs = w, h
        markers = detector.detect(frame)

        if markers:
            frames_with_marker += 1
            m = max(markers, key=lambda x: x["size"])
            cx = m["center"][0]
            size = m["size"]
            pixel_sizes.append(size)
            dist = approach._distance_m(size, w)
            now = time.monotonic()
            if now - last_print >= 0.2:
                zone = ""
                if dist < approach.HOLD_NEAR_M:
                    zone = "TOO CLOSE"
                elif dist <= approach.HOLD_FAR_M:
                    zone = "HOLD BAND"
                elif dist <= approach.APPROACH_REENGAGE_M:
                    zone = "near hold"
                else:
                    zone = "approach"
                print(f"t={now-t0:5.1f}  id={m['id']:3d}  cx={cx:6.1f}  "
                      f"size={size:6.1f}  dist={dist:.3f} m  "
                      f"fps={cam.actual_fps:5.1f}  [{zone}]")
                last_print = now
        else:
            now = time.monotonic()
            if now - last_print >= 1.0:
                print(f"t={now-t0:5.1f}  (no marker — frame={w}x{h}  "
                      f"fps={cam.actual_fps:5.1f})")
                last_print = now

        if args.seconds > 0 and (time.monotonic() - t0) >= args.seconds:
            break

    cam.close()

    elapsed = time.monotonic() - t0
    print()
    print("=" * 78)
    print(f"Actual frame size : {frame_w_obs}x{frame_h_obs} "
          f"(aspect {frame_w_obs/frame_h_obs:.3f})" if frame_w_obs else "no frames")
    print(f"Elapsed           : {elapsed:.1f} s")
    print(f"Frames read       : {frames_seen}  -> {frames_seen/elapsed:.1f} fps average")
    print(f"Frames w/ marker  : {frames_with_marker}")
    if pixel_sizes:
        pixel_sizes.sort()
        median = pixel_sizes[len(pixel_sizes)//2]
        print(f"Marker pixel size : median={median:.1f}  "
              f"min={pixel_sizes[0]:.1f}  max={pixel_sizes[-1]:.1f}")
    if frame_w_obs and frame_w_obs != rw:
        print(f"WARNING: got {frame_w_obs}x{frame_h_obs}, asked for {rw}x{rh} — "
              "the driver fell back to a different mode")
    if frame_w_obs and frame_h_obs:
        aspect = frame_w_obs / frame_h_obs
        if abs(aspect - 16/9) > 0.02 and abs(aspect - 4/3) < 0.02:
            print("WARNING: aspect is 4:3 — this mode likely crops the 160° FOV")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
