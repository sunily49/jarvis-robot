"""
Audio capture pipeline — 48kHz mic input → 16kHz resampled ring buffer.

Runs in a ThreadPoolExecutor to avoid blocking asyncio.
Provides chunks to wake word detector and Gemini Live.
"""

import asyncio
import logging
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import numpy as np
from scipy.signal import resample_poly

from jarvis.config import settings

logger = logging.getLogger(__name__)

# Resample ratio: 48000 → 16000 = 1/3
_DOWNSAMPLE_FACTOR = settings.AUDIO_SAMPLE_RATE // settings.AUDIO_TARGET_RATE


class AudioCapture:
    """Captures audio from the microphone and provides resampled 16kHz chunks."""

    def __init__(self) -> None:
        self._stream = None
        self._pa = None
        self._running = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio")
        self._lock = threading.Lock()

        # Ring buffer of 16kHz int16 chunks
        self._buffer: deque[np.ndarray] = deque(maxlen=100)
        self._chunk_event = asyncio.Event()

        # Subscribers for raw 16kHz chunks (wake word, Gemini Live, etc.)
        self._subscribers: list[Callable[[np.ndarray], None]] = []

    def add_subscriber(self, callback: Callable[[np.ndarray], None]) -> None:
        """Register a callback that receives every 16kHz chunk."""
        self._subscribers.append(callback)

    def remove_subscriber(self, callback: Callable[[np.ndarray], None]) -> None:
        """Unregister a previously added callback."""
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    async def start(self) -> None:
        """Start audio capture in a background thread."""
        if self._running:
            return
        self._running = True
        loop = asyncio.get_event_loop()
        loop.run_in_executor(self._executor, self._capture_loop)
        logger.info(
            "Audio capture started: %dHz → %dHz, chunk=%d",
            settings.AUDIO_SAMPLE_RATE,
            settings.AUDIO_TARGET_RATE,
            settings.AUDIO_CHUNK_SIZE,
        )

    def _capture_loop(self) -> None:
        """Blocking capture loop (runs in thread)."""
        import pyaudio

        self._pa = pyaudio.PyAudio()

        device_index = settings.AUDIO_DEVICE_INDEX
        if device_index < 0:
            device_index = None  # Let PyAudio choose default

        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=settings.AUDIO_SAMPLE_RATE,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=settings.AUDIO_CHUNK_SIZE,
        )

        while self._running:
            try:
                raw = self._stream.read(settings.AUDIO_CHUNK_SIZE, exception_on_overflow=False)
                samples_48k = np.frombuffer(raw, dtype=np.int16).astype(np.float32)

                # Resample 48kHz → 16kHz
                samples_16k = resample_poly(samples_48k, 1, _DOWNSAMPLE_FACTOR).astype(np.int16)

                with self._lock:
                    self._buffer.append(samples_16k)

                # Notify subscribers
                for cb in self._subscribers:
                    try:
                        cb(samples_16k)
                    except Exception:
                        logger.exception("Audio subscriber error")

            except Exception:
                if self._running:
                    logger.exception("Audio capture error")
                break

        self._cleanup()

    def _cleanup(self) -> None:
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        if self._pa:
            self._pa.terminate()

    async def stop(self) -> None:
        self._running = False
        self._executor.shutdown(wait=False)
        logger.info("Audio capture stopped")

    def get_recent_chunks(self, n: int = 10) -> list[np.ndarray]:
        """Get the last N chunks from the ring buffer."""
        with self._lock:
            return list(self._buffer)[-n:]

    def get_raw_bytes(self, n_chunks: int = 1) -> bytes:
        """Get raw 16kHz PCM bytes for Gemini Live streaming."""
        chunks = self.get_recent_chunks(n_chunks)
        if not chunks:
            return b""
        return np.concatenate(chunks).tobytes()


# Singleton
audio_capture = AudioCapture()
