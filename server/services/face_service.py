"""
Face Recognition Service — identifies faces from JPEG frames.

Backend is selected via FACE_RECOGNIZER_BACKEND env var (default "auto"):
  insightface — InsightFace ArcFace ONNX (preferred, 99.83% LFW)
  dlib        — face_recognition / dlib HOG (fallback, 99.38% LFW)

Stores known face encodings in faces.pkl alongside the backend name.
If the pkl was saved with a different backend, a warning is logged and
re-enrollment is recommended (embeddings live in incompatible spaces).
"""

import logging
import os
import pickle
from pathlib import Path

import cv2
import numpy as np

from services.face_recognizer import create_face_recognizer

logger = logging.getLogger(__name__)

FACES_DB = Path(__file__).parent.parent / "data" / "faces.pkl"


class FaceService:
    def __init__(self) -> None:
        self._recognizer = create_face_recognizer(
            os.getenv("FACE_RECOGNIZER_BACKEND", "auto")
        )
        self._known_encodings: list[np.ndarray] = []
        self._known_names: list[str] = []
        self._load_faces()

    def _load_faces(self) -> None:
        if FACES_DB.exists():
            with open(FACES_DB, "rb") as f:
                data = pickle.load(f)
            saved_backend = data.get("backend", "unknown")
            active_backend = type(self._recognizer).__name__
            if saved_backend != active_backend:
                logger.warning(
                    "faces.pkl was saved with %s but active backend is %s. "
                    "Embeddings may be incompatible — consider re-enrolling faces.",
                    saved_backend, active_backend,
                )
            self._known_encodings = data.get("encodings", [])
            self._known_names = data.get("names", [])
            logger.info("Loaded %d known faces (backend=%s)", len(self._known_names), saved_backend)
        else:
            logger.info("No faces.pkl found — starting fresh at %s", FACES_DB)

    def _save_faces(self) -> None:
        FACES_DB.parent.mkdir(parents=True, exist_ok=True)
        with open(FACES_DB, "wb") as f:
            pickle.dump({
                "encodings": self._known_encodings,
                "names": self._known_names,
                "backend": type(self._recognizer).__name__,
            }, f)

    def identify(self, jpeg_bytes: bytes) -> list[dict]:
        """Identify faces in a JPEG image. Returns list of {name, confidence, location}."""
        img_array = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if frame is None:
            return []

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        face_encodings = self._recognizer.encode(rgb)

        results = []
        for face_enc in face_encodings:
            match = self._recognizer.match(
                face_enc.embedding,
                self._known_encodings,
                self._known_names,
            )
            results.append({
                "name": match["name"] or "Unknown",
                "confidence": match["confidence"],
                "location": face_enc.bbox,
            })

        return results

    def list_registered(self) -> list[str]:
        """Return unique registered face names in insertion order."""
        return list(dict.fromkeys(self._known_names))

    def rename(self, old_name: str, new_name: str) -> int:
        """Rename all face encodings from old_name to new_name. Returns count updated."""
        count = 0
        for i, name in enumerate(self._known_names):
            if name.lower() == old_name.lower():
                self._known_names[i] = new_name
                count += 1
        if count:
            self._save_faces()
        return count

    def register_face(self, name: str, jpeg_bytes: bytes) -> bool:
        """Register a new face from a JPEG image."""
        img_array = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if frame is None:
            return False

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        face_encodings = self._recognizer.encode(rgb)

        if not face_encodings:
            logger.warning("No face found in image for registration")
            return False

        self._known_encodings.append(face_encodings[0].embedding)
        self._known_names.append(name)
        self._save_faces()
        logger.info("Registered face: %s (total: %d)", name, len(self._known_names))
        return True
