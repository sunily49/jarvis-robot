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
        self._loop: asyncio.AbstractEventLoop | None = None

    def _on_audio_chunk(self, chunk: np.ndarray) -> None:
        """Callback from AudioCapture thread — thread-safe schedule into event loop."""
        if self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._chunk_queue.put_nowait, chunk)
        except (RuntimeError, asyncio.QueueFull):
            pass  # Loop closed or queue full — drop chunk

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
            wakeword_model_paths=[str(model_path)],
            inference_framework="onnx",
        )

        self._loop = asyncio.get_running_loop()
        from jarvis.audio.capture import audio_capture
        audio_capture.add_subscriber(self._on_audio_chunk)

        self._running = True
        logger.info("Wake word trigger started (threshold=%.2f)", settings.WAKEWORD_THRESHOLD)

        _debug_log_interval = 50   # log scores every N chunks when DEBUG
        _chunk_count = 0

        while self._running:
            try:
                chunk = await asyncio.wait_for(self._chunk_queue.get(), timeout=1.0)
                prediction = self._model.predict(chunk)
                _chunk_count += 1

                for model_name, score in prediction.items():
                    # Always log non-trivial scores so we can tune the threshold
                    if score > 0.1:
                        logger.debug("Wake word score: %s=%.3f (threshold=%.2f)",
                                     model_name, score, settings.WAKEWORD_THRESHOLD)
                    elif _chunk_count % _debug_log_interval == 0:
                        logger.debug("Wake word listening… chunk=%d, %s=%.4f",
                                     _chunk_count, model_name, score)

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
