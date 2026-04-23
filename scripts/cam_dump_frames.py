#!/usr/bin/env python3
"""Capture one raw MJPG frame at 1080p and one at 720p, save to disk,
and report what the ArUco detector sees (with default params and with
aggressive/fine-grained params for low-contrast edges)."""
import sys, os, time, cv2
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from alfred.vision.aruco import ArucoDetector

OUT = os.path.join(os.path.dirname(__file__), "..", "photos")
os.makedirs(OUT, exist_ok=True)


def grab(w, h, fps):
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    # warm up — let AE settle
    for _ in range(30):
        cap.read()
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None
    return frame


def inspect(frame, label):
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    print(f"\n[{label}] size={w}x{h} brightness mean={gray.mean():.0f} std={gray.std():.0f}")

    # Default detector
    det = ArucoDetector()
    markers = det.detect(frame)
    print(f"  default detect: {len(markers)} markers "
          f"{[(m['id'], round(m['size'],1)) for m in markers]}")

    # Raw cv2 ArUco with default + tuned params
    try:
        # Prefer new API
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        params = cv2.aruco.DetectorParameters()
        # Tighten adaptive threshold for softer edges from MJPG-compressed 720p
        params.adaptiveThreshWinSizeMin = 3
        params.adaptiveThreshWinSizeMax = 23
        params.adaptiveThreshWinSizeStep = 5
        params.minMarkerPerimeterRate = 0.02   # allow smaller markers
        params.polygonalApproxAccuracyRate = 0.05
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        # New-API ArucoDetector
        detector = cv2.aruco.ArucoDetector(dictionary, params)
        corners, ids, _ = detector.detectMarkers(frame)
        n = 0 if ids is None else len(ids)
        if ids is not None:
            flat_ids = [int(i) for i in ids.flatten()]
        else:
            flat_ids = []
        print(f"  tuned detect : {n} markers  ids={flat_ids}")
    except Exception as e:
        print(f"  tuned detect failed: {e}")

    # Save
    out_path = os.path.join(OUT, f"probe_{label.replace(' ','_').replace('/','-')}.jpg")
    cv2.imwrite(out_path, frame)
    print(f"  saved: {out_path}")


for (w, h, fps, label) in [(1920, 1080, 30, "1080p_30"),
                           (1280,  720, 30, "720p_30req"),
                           (1280,  720, 60, "720p_60req")]:
    f = grab(w, h, fps)
    if f is None:
        print(f"[{label}] capture failed")
        continue
    inspect(f, label)
    time.sleep(0.3)
