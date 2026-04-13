"""
Wake Word Trigger — openWakeWord v0.4.0 ONNX model.

Listens on the shared 16kHz audio stream for "hey jarvis" (or custom phrase).
~15% CPU on Pi 5.
"""

import asyncio
import logging

import numpy as np

from jarvis.config import settings
from jarvis.core.trigger_manager import BaseTrigger, TriggerPriority

logger = logging.getLogger(__name__)


class WakeWordTrigger(BaseTrigger):
    name = "wakeword"
    priority = TriggerPriority.NORMAL

    def __init__(self) -> None:
        self._model = None
        self._running = False
        self._chunk_queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=50)

    def _on_audio_chunk(self, chunk: np.ndarray) -> None:
        """Callback from AudioCapture — non-blocking put into queue."""
        try:
            self._chunk_queue.put_nowait(chunk)
        except asyncio.QueueFull:
            pass  # Drop oldest if behind

    async def start(self) -> None:
        """Start wake word detection loop."""
        import sys
        from pathlib import Path

        # Clear any previously broken/partial openwakeword module from cache
        # (happens when sklearn is missing on first import)
        for key in list(sys.modules.keys()):
            if "openwakeword" in key:
                del sys.modules[key]

        model_path = Path(settings.WAKEWORD_MODEL_PATH)
        if not model_path.exists():
            logger.error(
                "Wake word model not found: %s — run make install to download models",
                model_path,
            )
            await asyncio.sleep(60)
            return

        try:
            from openwakeword.model import Model
        except ModuleNotFoundError as e:
            logger.error("openwakeword import failed (%s) — install missing deps: pip install scikit-learn", e)
            await asyncio.sleep(60)
            return

        self._model = Model(
            wakeword_models=[str(model_path)],
            inference_framework="onnx",
        )

        from jarvis.audio.capture import audio_capture
        audio_capture.add_subscriber(self._on_audio_chunk)

        self._running = True
        logger.info("Wake word trigger started (threshold=%.2f)", settings.WAKEWORD_THRESHOLD)

        while self._running:
            try:
                chunk = await asyncio.wait_for(self._chunk_queue.get(), timeout=1.0)
                prediction = self._model.predict(chunk)

                for model_name, score in prediction.items():
                    if score >= settings.WAKEWORD_THRESHOLD:
                        logger.info("Wake word detected: %s (score=%.3f)", model_name, score)
                        await self.fire(confidence=score, data={"model": model_name})
                        self._model.reset()
                        # Brief pause after detection to avoid re-trigger
                        await asyncio.sleep(1.0)
                        break
            except asyncio.TimeoutError:
                continue

    async def stop(self) -> None:
        self._running = False
        logger.info("Wake word trigger stopped")


if settings.TRIGGER_WAKEWORD:
    from jarvis.core.trigger_manager import TriggerManager
    TriggerManager.register(WakeWordTrigger())
