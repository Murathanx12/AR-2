"""YOLO object detector — offline real-time obstacle and person detection.

Uses YOLOv8n (nano) for fast inference on Raspberry Pi 5.
Detects 80 COCO classes including person, chair, bottle, cup, etc.
Runs at ~5-10 FPS on Pi 5 CPU. No API cost.

Install: pip install ultralytics
"""

import logging
import time

logger = logging.getLogger(__name__)

_yolo_model = None
_HAS_YOLO = False

try:
    from ultralytics import YOLO
    _HAS_YOLO = True
except ImportError:
    pass

# Classes relevant for butler navigation
OBSTACLE_CLASSES = {
    "person", "chair", "couch", "table", "bench", "backpack", "suitcase",
    "bottle", "cup", "bowl", "potted plant", "bed", "dining table",
    "tv", "laptop", "refrigerator", "book", "vase", "scissors",
}

PERSON_CLASS = "person"


class YOLODetector:
    """Real-time object detection using YOLOv8n.

    Provides:
    - detect(): full detection with bounding boxes, classes, confidence
    - is_path_clear(): check if center path is blocked
    - get_people(): get detected person positions
    - get_obstacles(): get detected obstacles
    """

    def __init__(self, model_name="yolov8n", confidence=0.4):
        """
        Args:
            model_name: YOLO model variant. "yolov8n" is fastest for Pi.
            confidence: Minimum confidence threshold (0-1).
        """
        global _yolo_model
        self._conf = confidence
        self._model = None
        self._last_detections = []
        self._last_time = 0

        if not _HAS_YOLO:
            logger.warning("ultralytics not installed — YOLO unavailable. Install: pip install ultralytics")
            return

        try:
            if _yolo_model is None:
                logger.info(f"Loading {model_name} model...")
                _yolo_model = YOLO(model_name + ".pt")
                logger.info(f"YOLO {model_name} loaded")
            self._model = _yolo_model
        except Exception as e:
            logger.warning(f"YOLO load failed: {e}")

    @property
    def is_available(self):
        return self._model is not None

    def detect(self, frame):
        """Run detection on a frame.

        Returns list of dicts:
            [{"class": "person", "confidence": 0.85, "bbox": (x, y, w, h), "center": (cx, cy)}]
        """
        if not self._model:
            return []

        try:
            results = self._model(frame, conf=self._conf, verbose=False)
            detections = []
            for r in results:
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    cls_name = self._model.names[cls_id]
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    x, y, w, h = int(x1), int(y1), int(x2 - x1), int(y2 - y1)
                    cx, cy = x + w // 2, y + h // 2
                    detections.append({
                        "class": cls_name,
                        "confidence": conf,
                        "bbox": (x, y, w, h),
                        "center": (cx, cy),
                    })
            self._last_detections = detections
            self._last_time = time.monotonic()
            return detections
        except Exception as e:
            logger.warning(f"YOLO detect error: {e}")
            return []

    def get_people(self, frame=None):
        """Get detected people from last or new frame."""
        dets = self.detect(frame) if frame is not None else self._last_detections
        return [d for d in dets if d["class"] == PERSON_CLASS]

    def get_obstacles(self, frame=None):
        """Get detected obstacles (non-person objects in path)."""
        dets = self.detect(frame) if frame is not None else self._last_detections
        return [d for d in dets if d["class"] in OBSTACLE_CLASSES and d["class"] != PERSON_CLASS]

    def is_path_clear(self, frame, center_width_ratio=0.5):
        """Check if the center of the frame is free of obstacles.

        Args:
            frame: Camera frame.
            center_width_ratio: Fraction of frame width to check (0.5 = center 50%).

        Returns:
            True if path is clear.
        """
        dets = self.detect(frame)
        if not dets:
            return True

        h, w = frame.shape[:2]
        left = int(w * (0.5 - center_width_ratio / 2))
        right = int(w * (0.5 + center_width_ratio / 2))
        bottom_half_y = h // 2

        for d in dets:
            if d["class"] not in OBSTACLE_CLASSES:
                continue
            bx, by, bw, bh = d["bbox"]
            obj_cx = bx + bw // 2
            obj_bottom = by + bh
            if left < obj_cx < right and obj_bottom > bottom_half_y:
                return False
        return True

    def draw_detections(self, frame, detections=None):
        """Draw bounding boxes on frame (for debug display)."""
        try:
            import cv2
        except ImportError:
            return frame

        dets = detections or self._last_detections
        for d in dets:
            x, y, w, h = d["bbox"]
            cls = d["class"]
            conf = d["confidence"]
            color = (0, 255, 0) if cls == PERSON_CLASS else (0, 165, 255)
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            cv2.putText(frame, f"{cls} {conf:.0%}",
                       (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        return frame
