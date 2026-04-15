"""
Face Recognition — modular backend system.

Backends (preference order when backend="auto"):
  insightface — InsightFace ArcFace ONNX (99.83% LFW, multi-angle, preferred)
  dlib        — face_recognition / dlib HOG (99.38% LFW, frontal-only, fallback)

Usage:
  from services.face_recognizer import create_face_recognizer

  rec = create_face_recognizer()              # auto-selects best available
  rec = create_face_recognizer("insightface") # force InsightFace
  rec = create_face_recognizer("dlib")        # force dlib

  encodings = rec.encode(frame_rgb)           # list[FaceEncoding]
  result    = rec.match(enc.embedding, known_embeddings, names)
             # → {"name": str|None, "confidence": float}

Adding a new backend:
  1. Subclass BaseFaceRecognizer, implement encode() + distance() + match_threshold
  2. Add to BACKEND_REGISTRY
  3. Prepend to _AUTO_ORDER if it should be preferred
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

# ── Backend registry ───────────────────────────────────────────────────────────
BACKEND_REGISTRY: dict[str, tuple] = {
    "insightface": (lambda: InsightFaceRecognizer, "insightface"),
    "dlib":        (lambda: DlibFaceRecognizer,    "face_recognition"),
}
_AUTO_ORDER = ["insightface", "dlib"]


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class FaceEncoding:
    """A detected face with its embedding vector and bounding box."""
    embedding: np.ndarray
    bbox: dict  # {top, right, bottom, left} in pixels
    detection_confidence: float = 1.0


# ── Abstract base ──────────────────────────────────────────────────────────────

class BaseFaceRecognizer(ABC):
    """Abstract face recognizer. Subclass this to add a new backend."""

    @property
    @abstractmethod
    def match_threshold(self) -> float:
        """Max distance (or min similarity) considered a match."""

    @abstractmethod
    def encode(self, frame_rgb: np.ndarray) -> list[FaceEncoding]:
        """
        Detect and encode all faces in an RGB frame.
        Returns a list of FaceEncoding (may be empty if no faces detected).
        """

    @abstractmethod
    def distance(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """Return a distance between two embeddings (lower = more similar)."""

    def match(
        self,
        embedding: np.ndarray,
        known_embeddings: list[np.ndarray],
        known_names: list[str],
    ) -> dict:
        """
        Find the best matching name for an embedding.
        Returns {"name": str|None, "confidence": float}.
        """
        if not known_embeddings:
            return {"name": None, "confidence": 0.0}

        distances = [self.distance(embedding, k) for k in known_embeddings]
        best_idx = int(np.argmin(distances))
        best_dist = distances[best_idx]

        if best_dist <= self.match_threshold:
            return {
                "name": known_names[best_idx],
                "confidence": round(1.0 - best_dist, 3),
            }
        return {"name": None, "confidence": round(1.0 - best_dist, 3)}


# ── InsightFace ArcFace (preferred) ───────────────────────────────────────────

class InsightFaceRecognizer(BaseFaceRecognizer):
    """
    InsightFace buffalo_l: RetinaFace detection + ArcFace recognition.
    Accuracy: 99.83% LFW. Handles tilted/partial faces. ONNX CPU inference.
    Requires: insightface>=0.7.3, onnxruntime>=1.17.0
    """

    def __init__(self, model_pack: str = "buffalo_l") -> None:
        import insightface
        from insightface.app import FaceAnalysis
        self._app = FaceAnalysis(
            name=model_pack,
            providers=["CPUExecutionProvider"],
        )
        self._app.prepare(ctx_id=0, det_size=(640, 640))
        logger.info("InsightFace recognizer loaded (model_pack=%s)", model_pack)

    @property
    def match_threshold(self) -> float:
        return 0.4  # cosine distance; InsightFace embeddings are L2-normalised

    def encode(self, frame_rgb: np.ndarray) -> list[FaceEncoding]:
        import cv2
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        faces = self._app.get(frame_bgr)
        result = []
        for face in faces:
            bbox = face.bbox.astype(int)  # [x1, y1, x2, y2]
            result.append(FaceEncoding(
                embedding=face.normed_embedding,
                bbox={
                    "top":    int(bbox[1]),
                    "right":  int(bbox[2]),
                    "bottom": int(bbox[3]),
                    "left":   int(bbox[0]),
                },
                detection_confidence=float(face.det_score),
            ))
        return result

    def distance(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        # Both embeddings are L2-normalised → cosine distance = 1 - dot product
        return float(1.0 - np.clip(np.dot(emb1, emb2), -1.0, 1.0))

    def __repr__(self) -> str:
        return "InsightFaceRecognizer(buffalo_l)"


# ── Dlib / face_recognition (fallback) ────────────────────────────────────────

class DlibFaceRecognizer(BaseFaceRecognizer):
    """
    face_recognition (dlib HOG + ResNet): frontal-only detection.
    Accuracy: 99.38% LFW. Well-tested, good fallback.
    Requires: face_recognition>=1.3.0
    """

    @property
    def match_threshold(self) -> float:
        return 0.5  # Euclidean distance threshold (face_recognition default)

    def encode(self, frame_rgb: np.ndarray) -> list[FaceEncoding]:
        import face_recognition
        locations = face_recognition.face_locations(frame_rgb, model="hog")
        embeddings = face_recognition.face_encodings(frame_rgb, locations)
        result = []
        for emb, loc in zip(embeddings, locations):
            top, right, bottom, left = loc
            result.append(FaceEncoding(
                embedding=emb,
                bbox={"top": top, "right": right, "bottom": bottom, "left": left},
                detection_confidence=1.0,  # dlib doesn't return a score
            ))
        return result

    def distance(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        return float(np.linalg.norm(emb1 - emb2))

    def __repr__(self) -> str:
        return "DlibFaceRecognizer(hog)"


# ── Factory ────────────────────────────────────────────────────────────────────

def create_face_recognizer(backend: str = "auto") -> BaseFaceRecognizer:
    """
    Instantiate a face recognizer backend.

    Args:
        backend: "auto" | "insightface" | "dlib"

    Returns:
        A BaseFaceRecognizer instance.

    "auto" tries backends in _AUTO_ORDER and uses the first that loads successfully.
    """
    if backend != "auto":
        if backend not in BACKEND_REGISTRY:
            raise ValueError(f"Unknown face recognizer backend {backend!r}. "
                             f"Available: {list(BACKEND_REGISTRY)}")
        cls_fn, pkg = BACKEND_REGISTRY[backend]
        try:
            return cls_fn()()
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load face recognizer backend {backend!r} "
                f"— pip install {pkg}"
            ) from exc

    for name in _AUTO_ORDER:
        cls_fn, pkg = BACKEND_REGISTRY[name]
        try:
            instance = cls_fn()()
            logger.info("Face recognizer backend: %s", name)
            return instance
        except Exception as exc:
            logger.debug("Face recognizer backend %r not available (%s)", name, exc)

    raise RuntimeError("No face recognizer backend could be loaded. "
                       "Install face_recognition: pip install face-recognition")
