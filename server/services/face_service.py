"""
Face Recognition Service — identifies faces from JPEG frames.

Uses face_recognition library (dlib-based). Stores known face encodings in faces.pkl.
"""

import logging
import pickle
from pathlib import Path

import cv2
import face_recognition
import numpy as np

logger = logging.getLogger(__name__)

FACES_DB = Path(__file__).parent.parent / "data" / "faces.pkl"
TOLERANCE = 0.5


class FaceService:
    def __init__(self) -> None:
        self._known_encodings: list[np.ndarray] = []
        self._known_names: list[str] = []
        self._load_faces()

    def _load_faces(self) -> None:
        if FACES_DB.exists():
            with open(FACES_DB, "rb") as f:
                data = pickle.load(f)
            self._known_encodings = data.get("encodings", [])
            self._known_names = data.get("names", [])
            logger.info("Loaded %d known faces", len(self._known_names))
        else:
            logger.info("No faces.pkl found — starting fresh at %s", FACES_DB)

    def _save_faces(self) -> None:
        FACES_DB.parent.mkdir(parents=True, exist_ok=True)
        with open(FACES_DB, "wb") as f:
            pickle.dump({
                "encodings": self._known_encodings,
                "names": self._known_names,
            }, f)

    def identify(self, jpeg_bytes: bytes) -> list[dict]:
        """Identify faces in a JPEG image. Returns list of {name, confidence, location}."""
        img_array = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if frame is None:
            return []

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Detect and encode faces
        locations = face_recognition.face_locations(rgb, model="hog")
        encodings = face_recognition.face_encodings(rgb, locations)

        results = []
        for encoding, location in zip(encodings, locations):
            name = "Unknown"
            confidence = 0.0

            if self._known_encodings:
                distances = face_recognition.face_distance(self._known_encodings, encoding)
                best_idx = int(np.argmin(distances))
                best_distance = distances[best_idx]

                if best_distance < TOLERANCE:
                    name = self._known_names[best_idx]
                    confidence = round(1.0 - best_distance, 3)

            top, right, bottom, left = location
            results.append({
                "name": name,
                "confidence": confidence,
                "location": {"top": top, "right": right, "bottom": bottom, "left": left},
            })

        return results

    def register_face(self, name: str, jpeg_bytes: bytes) -> bool:
        """Register a new face from a JPEG image."""
        img_array = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if frame is None:
            return False

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        encodings = face_recognition.face_encodings(rgb)

        if not encodings:
            logger.warning("No face found in image for registration")
            return False

        self._known_encodings.append(encodings[0])
        self._known_names.append(name)
        self._save_faces()
        logger.info("Registered face: %s (total: %d)", name, len(self._known_names))
        return True
