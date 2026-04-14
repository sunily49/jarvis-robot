"""
Audio playback — unified speaker output for Gemini Live audio and Piper TTS.

Manages a single persistent output stream to avoid ALSA underruns.
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
    """Async audio playback with a persistent PyAudio output stream."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playback")
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._playing = False
        self._running = False
        self._pa = None
        self._stream = None
        self._stream_rate: int = 0
        self._interrupt = asyncio.Event()

    async def start(self) -> None:
        self._running = True
        asyncio.create_task(self._playback_loop())
        logger.info("Audio playback started")

    async def stop(self) -> None:
        self._running = False
        self._interrupt.set()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._close_stream)
        self._executor.shutdown(wait=False)
        logger.info("Audio playback stopped")

    def _close_stream(self) -> None:
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    async def play(
        self,
        audio_data: bytes,
        sample_rate: int = 24000,
        priority: PlaybackPriority = PlaybackPriority.CONVERSATION,
    ) -> None:
        """Queue audio for playback. Higher priority plays first."""
        await self._queue.put((-priority, audio_data, sample_rate))

    async def play_gemini_chunk(self, chunk: bytes, sample_rate: int = 24000) -> None:
        """Play a streaming Gemini Live audio chunk via the persistent output stream."""
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

    def _get_or_open_stream(self, sample_rate: int):
        """Return the persistent output stream, opening (or re-opening) as needed."""
        import pyaudio

        if not self._pa:
            self._pa = pyaudio.PyAudio()

        if self._stream is None or self._stream_rate != sample_rate:
            if self._stream is not None:
                try:
                    self._stream.stop_stream()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

            # frames_per_buffer=4096 gives ALSA a larger buffer, preventing underruns
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=sample_rate,
                output=True,
                frames_per_buffer=4096,
            )
            self._stream_rate = sample_rate
            logger.debug("Opened output stream at %dHz (buf=4096)", sample_rate)

        return self._stream

    def _play_raw(self, audio_data: bytes, sample_rate: int) -> None:
        """Blocking playback of raw PCM audio (runs in executor thread).

        Uses a persistent stream — opening once and writing many chunks to it
        eliminates the ALSA underruns caused by repeated open/close cycles.
        """
        try:
            stream = self._get_or_open_stream(sample_rate)

            # Write in 4096-sample chunks (8192 bytes); small enough for low
            # latency, large enough to keep ALSA happy.
            WRITE_SIZE = 4096 * 2  # bytes (4096 int16 samples)
            offset = 0
            while offset < len(audio_data):
                if self._interrupt.is_set():
                    self._interrupt.clear()
                    break
                end = min(offset + WRITE_SIZE, len(audio_data))
                stream.write(audio_data[offset:end])
                offset = end

        except Exception:
            logger.exception("Raw playback error")
            self._stream = None  # Force stream re-open on next call


# Singleton
audio_playback = AudioPlayback()
