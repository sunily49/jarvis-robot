"""
Audio playback — unified speaker output for Gemini Live audio and Piper TTS.

Manages a single output stream with an async queue to prevent overlaps.
Gemini Live audio has priority over TTS announcements.
"""

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from enum import IntEnum

import numpy as np

from jarvis.config import settings

logger = logging.getLogger(__name__)


class PlaybackPriority(IntEnum):
    SYSTEM = 10       # System announcements (Piper TTS)
    CONVERSATION = 50  # Gemini Live audio stream
    ALERT = 90        # Emergency alerts


class AudioPlayback:
    """Async audio playback with priority queue."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playback")
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._playing = False
        self._running = False
        self._pa = None
        self._stream = None
        self._interrupt = asyncio.Event()

    async def start(self) -> None:
        self._running = True
        asyncio.create_task(self._playback_loop())
        logger.info("Audio playback started")

    async def stop(self) -> None:
        self._running = False
        self._interrupt.set()
        self._executor.shutdown(wait=False)
        logger.info("Audio playback stopped")

    async def play(
        self,
        audio_data: bytes,
        sample_rate: int = 24000,
        priority: PlaybackPriority = PlaybackPriority.CONVERSATION,
    ) -> None:
        """Queue audio for playback. Higher priority plays first."""
        await self._queue.put((-priority, audio_data, sample_rate))

    async def play_gemini_chunk(self, chunk: bytes, sample_rate: int = 24000) -> None:
        """Play a streaming Gemini Live audio chunk immediately."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._play_raw, chunk, sample_rate)

    async def interrupt(self) -> None:
        """Interrupt current playback (e.g., user spoke during response)."""
        self._interrupt.set()

    async def _playback_loop(self) -> None:
        """Process playback queue."""
        while self._running:
            try:
                neg_priority, audio_data, sample_rate = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    self._executor, self._play_raw, audio_data, sample_rate
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Playback error")

    def _play_raw(self, audio_data: bytes, sample_rate: int) -> None:
        """Blocking playback of raw PCM audio (runs in thread)."""
        import pyaudio

        if not self._pa:
            self._pa = pyaudio.PyAudio()

        try:
            stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=sample_rate,
                output=True,
            )

            # Play in chunks to allow interruption
            chunk_size = sample_rate * 2  # 1 second of int16
            offset = 0
            while offset < len(audio_data):
                if self._interrupt.is_set():
                    self._interrupt.clear()
                    break
                end = min(offset + chunk_size, len(audio_data))
                stream.write(audio_data[offset:end])
                offset = end

            stream.stop_stream()
            stream.close()
        except Exception:
            logger.exception("Raw playback error")


# Singleton
audio_playback = AudioPlayback()
