"""
Voice Activity Detection — modular backend system.

Backends (preference order when backend="auto"):
  silero  — SileroVAD via torch.hub (neural, noise-robust, ~5ms/chunk, ONNX on ARM)
  energy  — EnergyVAD (RMS threshold, no extra deps, always available — fallback)

Usage:
  from jarvis.audio.vad import create_vad

  vad = create_vad()            # auto-selects best available
  vad = create_vad("silero")    # force silero
  vad = create_vad("energy")    # force energy

  vad.reset()                   # call before each new utterance
  is_speech = vad.is_speech(pcm_int16_chunk)

Adding a new backend:
  1. Subclass BaseVAD and implement is_speech() + reset()
  2. Add to BACKEND_REGISTRY
  3. Prepend to _AUTO_ORDER if it should be preferred
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import numpy as np

logger = logging.getLogger(__name__)

# ── Backend registry ───────────────────────────────────────────────────────────
# Maps backend name → (class, pip_package_for_error_msg)
BACKEND_REGISTRY: dict[str, tuple] = {
    "silero": (lambda: SileroVAD,  "torch"),
    "energy": (lambda: EnergyVAD,  None),
}
_AUTO_ORDER = ["silero", "energy"]


# ── Abstract base ──────────────────────────────────────────────────────────────

class BaseVAD(ABC):
    """Abstract voice activity detector."""

    @abstractmethod
    def is_speech(self, pcm_int16: np.ndarray) -> bool:
        """Return True if the chunk contains speech."""

    @abstractmethod
    def reset(self) -> None:
        """Reset internal state before a new utterance."""


# ── Energy VAD (always available) ─────────────────────────────────────────────

class EnergyVAD(BaseVAD):
    """
    Simple RMS energy threshold.
    No extra dependencies — always available as a fallback.
    """
    def __init__(self, threshold: int = 400) -> None:
        self._threshold = threshold

    def is_speech(self, pcm_int16: np.ndarray) -> bool:
        rms = int(np.sqrt(np.mean(pcm_int16.astype(np.float32) ** 2)))
        return rms >= self._threshold

    def reset(self) -> None:
        pass  # stateless

    def __repr__(self) -> str:
        return f"EnergyVAD(threshold={self._threshold})"


# ── Silero VAD ─────────────────────────────────────────────────────────────────

class SileroVAD(BaseVAD):
    """
    Silero VAD — neural voice activity detection via torch.hub.
    Uses ONNX mode for fast inference on ARM (Pi 5).

    EER: significantly lower than energy VAD; handles background noise well.
    Requires: torch>=2.0.0

    Chunk size must be exactly 512 samples at 16kHz (32ms).
    Shorter/longer chunks are zero-padded or truncated.
    """
    _CHUNK_SIZE = 512  # 32ms at 16kHz
    _SAMPLE_RATE = 16000

    def __init__(self, threshold: float = 0.5) -> None:
        import torch
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=True,
        )
        self._model = model
        self._threshold = threshold
        self.reset()
        logger.info("SileroVAD loaded (threshold=%.2f, onnx=True)", threshold)

    def is_speech(self, pcm_int16: np.ndarray) -> bool:
        import torch
        # Normalise to float32 [-1, 1]
        audio = pcm_int16.astype(np.float32) / 32768.0

        # Silero requires exactly _CHUNK_SIZE samples
        if len(audio) < self._CHUNK_SIZE:
            audio = np.pad(audio, (0, self._CHUNK_SIZE - len(audio)))
        elif len(audio) > self._CHUNK_SIZE:
            audio = audio[: self._CHUNK_SIZE]

        tensor = torch.from_numpy(audio).unsqueeze(0)
        with torch.no_grad():
            prob = self._model(tensor, self._SAMPLE_RATE).item()
        return prob >= self._threshold

    def reset(self) -> None:
        self._model.reset_states()

    def __repr__(self) -> str:
        return f"SileroVAD(threshold={self._threshold})"


# ── Factory ────────────────────────────────────────────────────────────────────

def create_vad(backend: str = "auto") -> BaseVAD:
    """
    Instantiate a VAD backend.

    Args:
        backend: "auto" | "silero" | "energy"

    Returns:
        A BaseVAD instance.

    "auto" tries backends in _AUTO_ORDER and uses the first that loads successfully.
    """
    if backend != "auto":
        if backend not in BACKEND_REGISTRY:
            raise ValueError(f"Unknown VAD backend {backend!r}. "
                             f"Available: {list(BACKEND_REGISTRY)}")
        cls_fn, pkg = BACKEND_REGISTRY[backend]
        try:
            return cls_fn()()
        except Exception as exc:
            hint = f" — pip install {pkg}" if pkg else ""
            raise RuntimeError(f"Failed to load VAD backend {backend!r}{hint}") from exc

    for name in _AUTO_ORDER:
        cls_fn, pkg = BACKEND_REGISTRY[name]
        try:
            instance = cls_fn()()
            logger.info("VAD backend: %s", name)
            return instance
        except Exception as exc:
            logger.debug("VAD backend %r not available (%s)", name, exc)

    raise RuntimeError("No VAD backend could be loaded — this should never happen "
                       "(EnergyVAD requires no extra dependencies).")
