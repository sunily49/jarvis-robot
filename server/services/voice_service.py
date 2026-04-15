"""
Voice Enrollment Service — speaker identification via voice embeddings.

Backend is selected via SPEAKER_ENCODER_BACKEND env var (default "auto"):
  ecapa_tdnn  — SpeechBrain ECAPA-TDNN (preferred, ~0.8% EER)
  resemblyzer — Resemblyzer d-vector (fallback, ~5% EER)

Stores known voice embeddings in voices.pkl alongside the backend name.
If the pkl was saved with a different backend, a warning is logged and
re-enrollment is recommended (embeddings live in incompatible spaces).

Flow:
1. Enroll: capture audio → extract embedding → store with name
2. Identify: audio chunk → extract embedding → similarity against known voices
"""

import logging
import os
import pickle
from pathlib import Path

import numpy as np

from services.speaker_encoder import create_speaker_encoder

logger = logging.getLogger(__name__)

VOICES_DB = Path(__file__).parent.parent / "data" / "voices.pkl"


class VoiceService:
    def __init__(self) -> None:
        self._encoder = create_speaker_encoder(
            os.getenv("SPEAKER_ENCODER_BACKEND", "auto")
        )
        self._known_embeddings: list[np.ndarray] = []
        self._known_names: list[str] = []
        self._load_voices()

    def _load_voices(self) -> None:
        if VOICES_DB.exists():
            with open(VOICES_DB, "rb") as f:
                data = pickle.load(f)
            saved_backend = data.get("backend", "unknown")
            active_backend = type(self._encoder).__name__
            if saved_backend != active_backend:
                logger.warning(
                    "voices.pkl was saved with %s but active backend is %s. "
                    "Embeddings may be incompatible — consider re-enrolling voices.",
                    saved_backend, active_backend,
                )
            self._known_embeddings = data.get("embeddings", [])
            self._known_names = data.get("names", [])
            logger.info("Loaded %d known voices (backend=%s)", len(self._known_names), saved_backend)
        else:
            logger.info("No voices.pkl found — starting fresh at %s", VOICES_DB)

    def _save_voices(self) -> None:
        VOICES_DB.parent.mkdir(parents=True, exist_ok=True)
        with open(VOICES_DB, "wb") as f:
            pickle.dump({
                "embeddings": self._known_embeddings,
                "names": self._known_names,
                "backend": type(self._encoder).__name__,
            }, f)

    def enroll(self, name: str, audio_pcm: np.ndarray, sample_rate: int = 16000) -> bool:
        """Enroll a speaker by name from PCM audio (at least 3-5 seconds recommended)."""
        if audio_pcm.dtype != np.float32:
            audio_pcm = audio_pcm.astype(np.float32) / 32768.0

        embedding = self._encoder.embed(audio_pcm, sample_rate)
        if embedding is None:
            logger.warning("Audio too short for voice enrollment")
            return False

        # Check if name already exists — update with averaged embedding
        for i, existing_name in enumerate(self._known_names):
            if existing_name.lower() == name.lower():
                averaged = (self._known_embeddings[i] + embedding) / 2.0
                norm = np.linalg.norm(averaged)
                self._known_embeddings[i] = averaged / norm if norm > 0 else averaged
                self._save_voices()
                logger.info("Updated voice profile: %s", name)
                return True

        self._known_embeddings.append(embedding)
        self._known_names.append(name)
        self._save_voices()
        logger.info("Enrolled voice: %s (total: %d)", name, len(self._known_names))
        return True

    def identify(self, audio_pcm: np.ndarray, sample_rate: int = 16000) -> dict:
        """Identify a speaker from PCM audio. Returns {name, confidence}."""
        if audio_pcm.dtype != np.float32:
            audio_pcm = audio_pcm.astype(np.float32) / 32768.0

        embedding = self._encoder.embed(audio_pcm, sample_rate)
        if embedding is None:
            return {"name": None, "confidence": 0.0}

        return self._encoder.match(embedding, self._known_embeddings, self._known_names)

    def list_enrolled(self) -> list[str]:
        """Return list of enrolled speaker names."""
        return list(set(self._known_names))

    def remove(self, name: str) -> bool:
        """Remove a speaker by name."""
        indices = [i for i, n in enumerate(self._known_names) if n.lower() == name.lower()]
        if not indices:
            return False
        for i in reversed(indices):
            self._known_embeddings.pop(i)
            self._known_names.pop(i)
        self._save_voices()
        logger.info("Removed voice: %s", name)
        return True
