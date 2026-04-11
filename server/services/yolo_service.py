"""
YOLO Object Detection Service — YOLOv8n/s via ultralytics.

On a server with decent CPU/GPU, can run YOLOv8s (small) instead of nano.
"""

import logging

import cv2
import numpy as np
from ultralytics import YOLO

logger = logging.getLogger(__name__)


class YOLOService:
    def __init__(self, model_name: str = "yolov8n.pt") -> None:
        self._model = YOLO(model_name)
        logger.info("YOLO service initialized with model: %s", model_name)

    def detect(self, jpeg_bytes: bytes, confidence: float = 0.4) -> list[dict]:
        """Detect objects in a JPEG image. Returns list of {class, confidence, bbox}."""
        img_array = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if frame is None:
            return []

        results = self._model(frame, conf=confidence, verbose=False)

        detections = []
        for result in results:
            for box in result.boxes:
                cls_id = int(box.cls[0])
                cls_name = self._model.names.get(cls_id, f"class_{cls_id}")
                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()

                detections.append({
                    "class": cls_name,
                    "confidence": round(conf, 3),
                    "bbox": {
                        "x1": int(x1), "y1": int(y1),
                        "x2": int(x2), "y2": int(y2),
                    },
                })

        return detections
