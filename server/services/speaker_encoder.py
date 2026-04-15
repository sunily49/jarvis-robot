"""
Speaker Encoder — modular backend system for voice embeddings.

Backends (preference order when backend="auto"):
  ecapa_tdnn  — SpeechBrain ECAPA-TDNN (0.8% EER, noise-robust, preferred)
  resemblyzer — Resemblyzer d-vector (~5% EER, lightweight, fallback)

Usage:
  from services.speaker_encoder import create_speaker_encoder

  enc = create_speaker_encoder()               # auto-selects best available
  enc = create_speaker_encoder("ecapa_tdnn")   # force ECAPA-TDNN
  enc = create_speaker_encoder("resemblyzer")  # force Resemblyzer

  emb    = enc.embed(audio_float32, sample_rate=16000)  # ndarray|None
  result = enc.match(emb, known_embeddings, names)
          # → {"name": str|None, "confidence": float}

Adding a new backend:
  1. Subclass BaseSpeakerEncoder, implement embed() + similarity() + match_threshold
  2. Add to BACKEND_REGISTRY
  3. Prepend to _AUTO_ORDER if it should be preferred
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import numpy as np

logger = logging.getLogger(__name__)

# ── Backend registry ───────────────────────────────────────────────────────────
BACKEND_REGISTRY: dict[str, tuple] = {
    "ecapa_tdnn":  (lambda: ECAPATDNNEncoder,   "speechbrain"),
    "resemblyzer": (lambda: ResemblyzerEncoder, "resemblyzer"),
}
_AUTO_ORDER = ["ecapa_tdnn", "resemblyzer"]


# ── Abstract base ──────────────────────────────────────────────────────────────

class BaseSpeakerEncoder(ABC):
    """Abstract speaker encoder. Subclass this to add a new backend."""

    @property
    @abstractmethod
    def match_threshold(self) -> float:
        """Minimum similarity score considered a match (0–1)."""

    @abstractmethod
    def embed(self, audio_float: np.ndarray, sample_rate: int = 16000) -> np.ndarray | None:
        """
        Extract a speaker embedding from float32 PCM audio normalised to [-1, 1].
        Returns None if audio is too short or cannot be processed.
        """

    @abstractmethod
    def similarity(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """Return a similarity score between two embeddings (higher = more similar)."""

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

        similarities = [self.similarity(embedding, k) for k in known_embeddings]
        best_idx = int(np.argmax(similarities))
        best_sim = similarities[best_idx]

        if best_sim >= self.match_threshold:
            return {
                "name": known_names[best_idx],
                "confidence": round(float(best_sim), 3),
            }
        return {"name": None, "confidence": round(float(best_sim), 3)}


# ── ECAPA-TDNN (preferred) ─────────────────────────────────────────────────────

class ECAPATDNNEncoder(BaseSpeakerEncoder):
    """
    SpeechBrain ECAPA-TDNN speaker embeddings.
    EER: ~0.8% on VoxCeleb1. Highly noise-robust.
    Model is downloaded on first use (~80 MB) to ~/.cache/torch/hub/speechbrain/.
    Requires: speechbrain>=1.0.0, torch>=2.0.0
    """
    _SOURCE = "speechbrain/spkrec-ecapa-voxceleb"

    def __init__(self) -> None:
        import torch
        from speechbrain.inference.speaker import EncoderClassifier
        self._classifier = EncoderClassifier.from_hparams(
            source=self._SOURCE,
            run_opts={"device": "cpu"},
        )
        self._torch = torch
        logger.info("ECAPA-TDNN speaker encoder loaded (%s)", self._SOURCE)

    @property
    def match_threshold(self) -> float:
        return 0.75  # cosine similarity threshold

    def embed(self, audio_float: np.ndarray, sample_rate: int = 16000) -> np.ndarray | None:
        if len(audio_float) < sample_rate:  # need at least 1 second
            return None
        if audio_float.dtype != np.float32:
            audio_float = audio_float.astype(np.float32)
        tensor = self._torch.tensor(audio_float).unsqueeze(0)
        with self._torch.no_grad():
            emb = self._classifier.encode_batch(tensor)
        # emb shape: [1, 1, 192] → flatten to [192]
        return emb.squeeze().cpu().numpy()

    def similarity(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        # Both are L2-normalised → cosine similarity = dot product
        n1 = np.linalg.norm(emb1)
        n2 = np.linalg.norm(emb2)
        if n1 == 0 or n2 == 0:
            return 0.0
        return float(np.clip(np.dot(emb1, emb2) / (n1 * n2), 0.0, 1.0))

    def __repr__(self) -> str:
        return "ECAPATDNNEncoder(speechbrain/spkrec-ecapa-voxceleb)"


# ── Resemblyzer (fallback) ─────────────────────────────────────────────────────

class ResemblyzerEncoder(BaseSpeakerEncoder):
    """
    Resemblyzer d-vector speaker embeddings.
    EER: ~5%. Lightweight, good baseline, no heavy dependencies.
    Requires: resemblyzer>=0.1.3
    """

    def __init__(self) -> None:
        from resemblyzer import VoiceEncoder
        self._encoder = VoiceEncoder()
        logger.info("Resemblyzer speaker encoder loaded")

    @property
    def match_threshold(self) -> float:
        return 0.75  # cosine similarity threshold

    def embed(self, audio_float: np.ndarray, sample_rate: int = 16000) -> np.ndarray | None:
        from resemblyzer import preprocess_wav
        if audio_float.dtype != np.float32:
            audio_float = audio_float.astype(np.float32)
        wav = preprocess_wav(audio_float, source_sr=sample_rate)
        if len(wav) < sample_rate:
            return None
        return self._encoder.embed_utterance(wav)

    def similarity(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        n1 = np.linalg.norm(emb1)
        n2 = np.linalg.norm(emb2)
        if n1 == 0 or n2 == 0:
            return 0.0
        return float(np.clip(np.dot(emb1, emb2) / (n1 * n2), 0.0, 1.0))

    def __repr__(self) -> str:
        return "ResemblyzerEncoder()"


# ── Factory ────────────────────────────────────────────────────────────────────

def create_speaker_encoder(backend: str = "auto") -> BaseSpeakerEncoder:
    """
    Instantiate a speaker encoder backend.

    Args:
        backend: "auto" | "ecapa_tdnn" | "resemblyzer"

    Returns:
        A BaseSpeakerEncoder instance.

    "auto" tries backends in _AUTO_ORDER and uses the first that loads successfully.
    """
    if backend != "auto":
        if backend not in BACKEND_REGISTRY:
            raise ValueError(f"Unknown speaker encoder backend {backend!r}. "
                             f"Available: {list(BACKEND_REGISTRY)}")
        cls_fn, pkg = BACKEND_REGISTRY[backend]
        try:
            return cls_fn()()
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load speaker encoder backend {backend!r} "
                f"— pip install {pkg}"
            ) from exc

    for name in _AUTO_ORDER:
        cls_fn, pkg = BACKEND_REGISTRY[name]
        try:
            instance = cls_fn()()
            logger.info("Speaker encoder backend: %s", name)
            return instance
        except Exception as exc:
            logger.debug("Speaker encoder backend %r not available (%s)", name, exc)

    raise RuntimeError("No speaker encoder backend could be loaded. "
                       "Install resemblyzer: pip install resemblyzer")
