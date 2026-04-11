"""
Voice Enrollment Service — speaker identification via voice embeddings.

Uses resemblyzer (d-vector) for speaker embeddings. Stores known voiceprints
in voices.pkl alongside face encodings.

Flow:
1. Enroll: capture audio → extract embedding → store with name
2. Identify: audio chunk → extract embedding → cosine similarity against known voices
"""

import logging
import pickle
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

VOICES_DB = Path(__file__).parent.parent / "data" / "voices.pkl"
SIMILARITY_THRESHOLD = 0.75  # cosine similarity threshold for match


class VoiceService:
    def __init__(self) -> None:
        self._known_embeddings: list[np.ndarray] = []
        self._known_names: list[str] = []
        self._encoder = None  # lazy-loaded
        self._load_voices()

    def _load_voices(self) -> None:
        if VOICES_DB.exists():
            with open(VOICES_DB, "rb") as f:
                data = pickle.load(f)
            self._known_embeddings = data.get("embeddings", [])
            self._known_names = data.get("names", [])
            logger.info("Loaded %d known voices", len(self._known_names))
        else:
            logger.info("No voices.pkl found — starting fresh at %s", VOICES_DB)

    def _save_voices(self) -> None:
        VOICES_DB.parent.mkdir(parents=True, exist_ok=True)
        with open(VOICES_DB, "wb") as f:
            pickle.dump({
                "embeddings": self._known_embeddings,
                "names": self._known_names,
            }, f)

    def _get_encoder(self):
        """Lazy-load the voice encoder to avoid slow startup."""
        if self._encoder is None:
            from resemblyzer import VoiceEncoder
            self._encoder = VoiceEncoder()
            logger.info("Voice encoder loaded")
        return self._encoder

    def _embed(self, audio_pcm: np.ndarray, sample_rate: int = 16000) -> np.ndarray | None:
        """Extract a d-vector embedding from PCM audio."""
        from resemblyzer import preprocess_wav
        # preprocess_wav expects float32 in [-1, 1]
        if audio_pcm.dtype != np.float32:
            audio_pcm = audio_pcm.astype(np.float32) / 32768.0
        wav = preprocess_wav(audio_pcm, source_sr=sample_rate)
        if len(wav) < sample_rate:  # need at least 1 second
            return None
        encoder = self._get_encoder()
        return encoder.embed_utterance(wav)

    def enroll(self, name: str, audio_pcm: np.ndarray, sample_rate: int = 16000) -> bool:
        """Enroll a speaker by name from PCM audio (at least 3-5 seconds recommended)."""
        embedding = self._embed(audio_pcm, sample_rate)
        if embedding is None:
            logger.warning("Audio too short for voice enrollment")
            return False

        # Check if name already exists — update with averaged embedding
        for i, existing_name in enumerate(self._known_names):
            if existing_name.lower() == name.lower():
                # Average with existing embedding for better accuracy
                self._known_embeddings[i] = (
                    self._known_embeddings[i] + embedding
                ) / 2.0
                self._known_embeddings[i] /= np.linalg.norm(self._known_embeddings[i])
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
        embedding = self._embed(audio_pcm, sample_rate)
        if embedding is None:
            return {"name": None, "confidence": 0.0}

        if not self._known_embeddings:
            return {"name": None, "confidence": 0.0}

        # Cosine similarity against all known voices
        similarities = [
            float(np.dot(embedding, known) / (np.linalg.norm(embedding) * np.linalg.norm(known)))
            for known in self._known_embeddings
        ]

        best_idx = int(np.argmax(similarities))
        best_sim = similarities[best_idx]

        if best_sim >= SIMILARITY_THRESHOLD:
            return {
                "name": self._known_names[best_idx],
                "confidence": round(best_sim, 3),
            }
        return {"name": None, "confidence": round(best_sim, 3)}

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
