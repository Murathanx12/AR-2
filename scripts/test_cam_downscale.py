#!/usr/bin/env python3
"""Full-FOV 720p via software downscale of native 1080p.

The Arducam's native 1280x720 mode hardware-crops the sensor (narrower
FOV, softer edges from line-skip readout). To get "720p-equivalent
compute cost" while keeping the full 160 degree FOV we:
  1. Capture at native 1920x1080 MJPG
  2. cv2.resize(INTER_AREA) -> 1280x720
  3. Run ArUco on the resized frame

Also captures:
  - Native 1080p baseline (no resize)
  - Native 720p (hardware crop) — for FOV comparison
  - Downscaled 1080p->720p — FOV preserved, detector runs on smaller image

Saves one probe frame of each for visual comparison.
"""
import sys, os, time, cv2
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from alfred.vision.aruco import ArucoDetector
from alfred.navigation.aruco_approach import ArucoApproach

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "photos")
os.makedirs(OUT_DIR, exist_ok=True)


def open_cam(w, h, fps):
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    # Warm up: Arducam AE needs ~20-30 frames to settle in low light
    for _ in range(30):
        cap.read()
    return cap


def bench(cap, label, seconds, detector, approach, post=None, save_name=None):
    print(f"\n=== {label} ===")
    aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    drv = cap.get(cv2.CAP_PROP_FPS)
    print(f"Sensor native : {aw}x{ah}  driver_fps={drv:.0f}")

    t0 = time.monotonic()
    frames = with_marker = 0
    sizes = []
    saved = False
    last_print = 0.0
    while time.monotonic() - t0 < seconds:
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        # Optional post-processing (e.g. resize)
        proc = post(frame) if post else frame
        frames += 1
        markers = detector.detect(proc)
        if markers:
            with_marker += 1
            m = max(markers, key=lambda x: x["size"])
            sizes.append(m["size"])
            now = time.monotonic()
            if now - last_print >= 0.4:
                d = approach._distance_m(m["size"], proc.shape[1])
                print(f"  t={now-t0:5.1f}  id={m['id']:3d}  "
                      f"size={m['size']:6.1f}  dist={d:.3f} m  frames={frames}")
                last_print = now
        # Save the first frame we see (post-processed) for FOV comparison
        if save_name and not saved:
            cv2.imwrite(os.path.join(OUT_DIR, save_name), proc)
            saved = True

    elapsed = time.monotonic() - t0
    fps = frames / max(elapsed, 0.001)
    print(f"Detect frame  : {proc.shape[1]}x{proc.shape[0]}")
    print(f"Result        : {frames} frames in {elapsed:.1f}s -> {fps:.1f} fps, "
          f"{with_marker} with marker ({100*with_marker/max(frames,1):.0f}%)")
    if sizes:
        sizes.sort()
        print(f"Pixel size    : median={sizes[len(sizes)//2]:.1f}  "
              f"min={sizes[0]:.1f}  max={sizes[-1]:.1f}")
    return {"fps": fps, "detect_rate": with_marker / max(frames, 1),
            "median_size": sizes[len(sizes)//2] if sizes else None,
            "frame_w": proc.shape[1], "frame_h": proc.shape[0]}


def main():
    detector = ArucoDetector()
    approach = ArucoApproach()

    # Run 1: 1080p native baseline
    cap = open_cam(1920, 1080, 30)
    r1080 = bench(cap, "1080p native MJPG (baseline)", 8, detector, approach,
                  save_name="probe2_1080p_native.jpg")
    cap.release()
    time.sleep(0.4)

    # Run 2: 720p hardware (crops FOV)
    cap = open_cam(1280, 720, 30)
    r720h = bench(cap, "720p native MJPG (HARDWARE CROP)", 8, detector, approach,
                  save_name="probe2_720p_hwcrop.jpg")
    cap.release()
    time.sleep(0.4)

    # Run 3: 1080p capture, downscaled to 720p in software -> FOV preserved
    cap = open_cam(1920, 1080, 30)
    def downscale(frame):
        return cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
    r720s = bench(cap, "1080p capture -> SW downscale to 720p (FULL FOV)",
                  8, detector, approach, post=downscale,
                  save_name="probe2_720p_sw_downscale.jpg")
    cap.release()

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for label, r in [("1080p native        ", r1080),
                     ("720p hw-crop        ", r720h),
                     ("720p sw-downscale   ", r720s)]:
        print(f"{label} fps={r['fps']:5.1f}  "
              f"detect={100*r['detect_rate']:5.1f}%  "
              f"size_px={r['median_size']}  "
              f"frame={r['frame_w']}x{r['frame_h']}")

    # Save scene comparison note
    print("\nProbe frames saved for FOV comparison:")
    for name in ("probe2_1080p_native.jpg",
                 "probe2_720p_hwcrop.jpg",
                 "probe2_720p_sw_downscale.jpg"):
        p = os.path.join(OUT_DIR, name)
        print(f"  {p}  ({os.path.getsize(p) if os.path.exists(p) else 0} bytes)")


if __name__ == "__main__":
    main()
