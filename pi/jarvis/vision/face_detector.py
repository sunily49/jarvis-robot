"""
Face Detector — modular face detection backend for the Pi.

Backends (auto-selected in order of preference):
  mediapipe  — BlazeFace, ~5 ms/frame on Pi 5, handles tilted/angled faces
  haar       — OpenCV Haar Cascade, always available, frontal faces only

Usage
-----
    detector = create_face_detector()           # auto: best available
    detector = create_face_detector("haar")     # force a specific backend
    faces    = detector.detect(bgr_frame)       # → list[FaceDetection]
    detector.close()                            # release resources on shutdown

Adding a new backend
--------------------
    1. Subclass BaseFaceDetector and implement detect() / close().
    2. Add an entry to BACKEND_REGISTRY.
    3. Prepend the name to _AUTO_ORDER if it should be preferred.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


# ── Data model ────────────────────────────────────────────────────────

@dataclass
class FaceDetection:
    """A single detected face."""
    bbox: tuple[int, int, int, int]  # (x, y, width, height) in pixels
    confidence: float                # 0.0 – 1.0

    @property
    def area(self) -> int:
        return self.bbox[2] * self.bbox[3]

    @property
    def center(self) -> tuple[int, int]:
        x, y, w, h = self.bbox
        return (x + w // 2, y + h // 2)


# ── Abstract base ─────────────────────────────────────────────────────

class BaseFaceDetector(ABC):
    """Interface that every face-detector backend must satisfy."""

    @abstractmethod
    def detect(self, frame_bgr: np.ndarray) -> list[FaceDetection]:
        """
        Detect faces in a BGR (OpenCV) frame.

        Args:
            frame_bgr: H×W×3 uint8 numpy array in BGR colour order.

        Returns:
            List of FaceDetection instances (may be empty).
        """

    def close(self) -> None:
        """Release any held resources (override if needed)."""


# ── Backend: OpenCV Haar Cascade ─────────────────────────────────────

class HaarCascadeDetector(BaseFaceDetector):
    """
    OpenCV frontal-face Haar Cascade.

    Always available (ships with opencv-python).
    Detects frontal faces well; struggles with tilts >30°.
    """

    def __init__(
        self,
        scale_factor: float = 1.2,
        min_neighbors: int = 5,
        min_size: tuple[int, int] = (60, 60),
    ) -> None:
        import cv2
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._cascade = cv2.CascadeClassifier(path)
        self._scale_factor = scale_factor
        self._min_neighbors = min_neighbors
        self._min_size = min_size

    def detect(self, frame_bgr: np.ndarray) -> list[FaceDetection]:
        import cv2
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(
            gray,
            scaleFactor=self._scale_factor,
            minNeighbors=self._min_neighbors,
            minSize=self._min_size,
        )
        if len(faces) == 0:
            return []
        return [
            FaceDetection(bbox=(int(x), int(y), int(w), int(h)), confidence=0.8)
            for (x, y, w, h) in faces
        ]


# ── Backend: MediaPipe BlazeFace ──────────────────────────────────────

class MediaPipeFaceDetector(BaseFaceDetector):
    """
    Google MediaPipe BlazeFace.

    ~5 ms/frame on Pi 5 (ARM-optimised TFLite).
    Handles tilted, angled, and partially occluded faces.
    Requires: pip install mediapipe

    model_selection:
        0 = short-range model (≤ 2 m, faster)  ← default for robot
        1 = full-range model  (≤ 5 m, slower)
    """

    def __init__(
        self,
        min_confidence: float = 0.5,
        model_selection: int = 0,
    ) -> None:
        import mediapipe as mp
        self._face_detection = mp.solutions.face_detection
        self._detector = self._face_detection.FaceDetection(
            model_selection=model_selection,
            min_detection_confidence=min_confidence,
        )
        logger.debug("MediaPipe BlazeFace detector ready (model=%d)", model_selection)

    def detect(self, frame_bgr: np.ndarray) -> list[FaceDetection]:
        import cv2
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        results = self._detector.process(rgb)

        detections: list[FaceDetection] = []
        if results.detections:
            h, w = frame_bgr.shape[:2]
            for det in results.detections:
                bb = det.location_data.relative_bounding_box
                x = max(0, int(bb.xmin * w))
                y = max(0, int(bb.ymin * h))
                fw = min(w - x, int(bb.width * w))
                fh = min(h - y, int(bb.height * h))
                detections.append(FaceDetection(
                    bbox=(x, y, fw, fh),
                    confidence=float(det.score[0]),
                ))
        return detections

    def close(self) -> None:
        self._detector.close()


# ── Registry & factory ────────────────────────────────────────────────

#: Map backend name → (class, pip_package_for_error_messages)
BACKEND_REGISTRY: dict[str, tuple[type[BaseFaceDetector], str]] = {
    "mediapipe": (MediaPipeFaceDetector, "mediapipe"),
    "haar":      (HaarCascadeDetector,   "opencv-python"),
}

#: Preference order when backend="auto"
_AUTO_ORDER = ["mediapipe", "haar"]


def create_face_detector(backend: str = "auto", **kwargs) -> BaseFaceDetector:
    """
    Create a face detector.

    Args:
        backend: One of "auto", "mediapipe", "haar".
                 "auto" tries backends in order and returns the first that works.
        **kwargs: Forwarded to the backend constructor.

    Returns:
        A ready-to-use BaseFaceDetector instance.

    Raises:
        ValueError:   Unknown backend name.
        RuntimeError: Requested backend not installable, or no backend available.
    """
    candidates = _AUTO_ORDER if backend == "auto" else [backend]

    for name in candidates:
        if name not in BACKEND_REGISTRY:
            raise ValueError(
                f"Unknown face detector backend: {name!r}. "
                f"Available: {sorted(BACKEND_REGISTRY)}"
            )
        cls, pkg = BACKEND_REGISTRY[name]
        try:
            det = cls(**kwargs)
            logger.info("Face detector: %s", name)
            return det
        except ImportError:
            if backend != "auto":
                raise RuntimeError(
                    f"Face detector '{name}' requires '{pkg}'. "
                    f"Install it: pip install {pkg}"
                ) from None
            logger.debug("Face detector '%s' unavailable (import error) — trying next", name)
        except Exception as exc:
            if backend != "auto":
                raise
            logger.debug("Face detector '%s' failed (%s) — trying next", name, exc)

    raise RuntimeError("No face detector backend could be initialised")
