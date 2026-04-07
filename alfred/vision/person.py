"""Person detection using MediaPipe — faces, hands, and gestures."""

import logging

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

try:
    import mediapipe as mp
    _HAS_MP = True
except ImportError:
    _HAS_MP = False
    logger.warning("mediapipe not installed — person detection unavailable")


class PersonDetector:
    """Detects faces and hands, classifies hand gestures using MediaPipe."""

    def __init__(self, min_face_confidence=0.5, min_hand_confidence=0.5):
        self._face_detection = None
        self._hand_detection = None

        if _HAS_MP:
            self._face_detection = mp.solutions.face_detection.FaceDetection(
                min_detection_confidence=min_face_confidence,
                model_selection=0,  # 0=short-range, 1=full-range
            )
            self._hand_detection = mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=2,
                min_detection_confidence=min_hand_confidence,
            )

    def detect_faces(self, frame):
        """Detect faces in a frame.

        Args:
            frame: BGR image.

        Returns:
            List of dicts: [{"bbox": (x,y,w,h), "confidence": float, "center": (cx,cy)}, ...]
        """
        if not _HAS_MP or not _HAS_CV2 or frame is None:
            return []

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._face_detection.process(rgb)

        faces = []
        if results.detections:
            h, w = frame.shape[:2]
            for det in results.detections:
                bbox = det.location_data.relative_bounding_box
                x = int(bbox.xmin * w)
                y = int(bbox.ymin * h)
                bw = int(bbox.width * w)
                bh = int(bbox.height * h)
                faces.append({
                    "bbox": (x, y, bw, bh),
                    "confidence": det.score[0],
                    "center": (x + bw // 2, y + bh // 2),
                })
        return faces

    def detect_hands(self, frame):
        """Detect hands in a frame.

        Args:
            frame: BGR image.

        Returns:
            List of dicts with "landmarks" (21 points), "handedness" ("Left"/"Right").
        """
        if not _HAS_MP or not _HAS_CV2 or frame is None:
            return []

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._hand_detection.process(rgb)

        hands = []
        if results.multi_hand_landmarks:
            h, w = frame.shape[:2]
            for i, hand_landmarks in enumerate(results.multi_hand_landmarks):
                landmarks = []
                for lm in hand_landmarks.landmark:
                    landmarks.append((int(lm.x * w), int(lm.y * h), lm.z))

                handedness = "Unknown"
                if results.multi_handedness and i < len(results.multi_handedness):
                    handedness = results.multi_handedness[i].classification[0].label

                hands.append({
                    "landmarks": landmarks,
                    "handedness": handedness,
                })
        return hands

    def get_gesture(self, hand):
        """Classify a gesture from hand landmarks.

        Simple finger-counting approach: checks which fingers are extended.

        Args:
            hand: Dict from detect_hands() with "landmarks".

        Returns:
            String gesture name: "fist", "open", "thumbs_up", "peace", "point", "wave"
        """
        if not hand or "landmarks" not in hand:
            return "unknown"

        lm = hand["landmarks"]
        if len(lm) < 21:
            return "unknown"

        # Finger tip and pip indices (MediaPipe hand landmarks)
        # Thumb: tip=4, ip=3; Index: tip=8, pip=6; Middle: tip=12, pip=10
        # Ring: tip=16, pip=14; Pinky: tip=20, pip=18

        def is_finger_extended(tip_idx, pip_idx):
            return lm[tip_idx][1] < lm[pip_idx][1]  # tip above pip = extended

        # Thumb uses x-axis (lateral movement)
        thumb_extended = abs(lm[4][0] - lm[2][0]) > abs(lm[3][0] - lm[2][0])
        index_ext = is_finger_extended(8, 6)
        middle_ext = is_finger_extended(12, 10)
        ring_ext = is_finger_extended(16, 14)
        pinky_ext = is_finger_extended(20, 18)

        fingers_up = sum([thumb_extended, index_ext, middle_ext, ring_ext, pinky_ext])

        if fingers_up == 0:
            return "fist"
        elif fingers_up == 5:
            return "open"
        elif thumb_extended and not index_ext and not middle_ext:
            return "thumbs_up"
        elif index_ext and middle_ext and not ring_ext and not pinky_ext:
            return "peace"
        elif index_ext and not middle_ext and not ring_ext:
            return "point"
        else:
            return "wave"

    def close(self):
        """Release MediaPipe resources."""
        if self._face_detection:
            self._face_detection.close()
        if self._hand_detection:
            self._hand_detection.close()
