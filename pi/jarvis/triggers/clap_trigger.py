"""
Clap/Snap Trigger — audio energy spike + frequency band filter.

Detects sharp transient sounds (claps, snaps). Supports double-clap pattern.
"""

import asyncio
import logging
import time

import numpy as np

from jarvis.config import settings
from jarvis.core.trigger_manager import BaseTrigger, TriggerPriority

logger = logging.getLogger(__name__)

# Clap detection parameters
ENERGY_THRESHOLD = 5000       # Minimum energy for a clap candidate
FREQUENCY_LOW = 2000          # Clap energy concentrated 2-8kHz
FREQUENCY_HIGH = 8000
DOUBLE_CLAP_WINDOW = 0.7     # Max seconds between two claps
DOUBLE_CLAP_MIN_GAP = 0.1    # Min seconds between two claps (debounce)


class ClapTrigger(BaseTrigger):
    name = "clap"
    priority = TriggerPriority.NORMAL

    def __init__(self) -> None:
        self._running = False
        self._chunk_queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=50)
        self._last_clap_time = 0.0
        self._clap_count = 0

    def _on_audio_chunk(self, chunk: np.ndarray) -> None:
        try:
            self._chunk_queue.put_nowait(chunk)
        except asyncio.QueueFull:
            pass

    async def start(self) -> None:
        from jarvis.audio.capture import audio_capture
        audio_capture.add_subscriber(self._on_audio_chunk)

        self._running = True
        logger.info("Clap trigger started")

        while self._running:
            try:
                chunk = await asyncio.wait_for(self._chunk_queue.get(), timeout=1.0)
                if self._is_clap(chunk):
                    now = time.time()
                    gap = now - self._last_clap_time

                    if DOUBLE_CLAP_MIN_GAP < gap < DOUBLE_CLAP_WINDOW:
                        self._clap_count += 1
                    else:
                        self._clap_count = 1

                    self._last_clap_time = now

                    if self._clap_count >= 2:
                        logger.info("Double clap detected!")
                        await self.fire(confidence=0.75, data={"pattern": "double_clap"})
                        self._clap_count = 0
            except asyncio.TimeoutError:
                # Reset clap count if too much time passes
                if time.time() - self._last_clap_time > DOUBLE_CLAP_WINDOW:
                    self._clap_count = 0

    def _is_clap(self, chunk: np.ndarray) -> bool:
        """Check if audio chunk contains a clap-like transient."""
        samples = chunk.astype(np.float32)
        energy = np.sqrt(np.mean(samples ** 2))
        if energy < ENERGY_THRESHOLD:
            return False

        # FFT to check frequency content
        fft = np.abs(np.fft.rfft(samples))
        freqs = np.fft.rfftfreq(len(samples), 1.0 / settings.AUDIO_TARGET_RATE)

        # Energy in clap frequency band vs. total
        band_mask = (freqs >= FREQUENCY_LOW) & (freqs <= FREQUENCY_HIGH)
        band_energy = np.sum(fft[band_mask])
        total_energy = np.sum(fft) + 1e-10

        ratio = band_energy / total_energy
        return ratio > 0.3  # At least 30% energy in clap band

    async def stop(self) -> None:
        self._running = False
        logger.info("Clap trigger stopped")


if settings.TRIGGER_CLAP:
    from jarvis.core.trigger_manager import TriggerManager
    TriggerManager.register(ClapTrigger())
