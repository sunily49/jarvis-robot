"""
Local Session — offline/LAN AI conversation without Gemini.

Pipeline per turn:
  AudioCapture (16kHz PCM) → VAD → Vosk STT → Ollama → Piper TTS → Speaker

Used in LOCAL_SERVER mode (WiFi but no internet) and OFFLINE mode (no network).
Mirrors GeminiLiveClient.run_session() signature so SessionManager can call
both interchangeably.

VAD (Voice Activity Detection):
  Energy-based threshold on int16 samples; no extra library required.
  Collects audio until OFFLINE_MAX_UTTERANCE_S seconds or silence detected.

STT:
  Vosk with vosk-model-small-en-us (45 MB, offline, ~0.1× real-time on Pi 5).
  Falls back to a scripted "no STT" message if model is not installed.

LLM:
  OllamaFallback.generate() — tries server Ollama first, then local phi3:mini.
  Falls back to a scripted response if Ollama is not installed.
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

from jarvis.audio.vad import create_vad
from jarvis.config import settings
from jarvis.core.event_bus import event_bus

logger = logging.getLogger(__name__)

# VAD tuning
_SILENCE_CHUNKS = 24   # ~0.75s of silence ends utterance (32ms chunks)
_MIN_SPEECH_CHUNKS = 4  # ignore utterances shorter than ~125ms

_SYSTEM_PROMPT = (
    "You are JARVIS, an AI robot assistant running locally on a Raspberry Pi 5. "
    "The internet may be unavailable. Be concise and helpful. "
    "Keep responses under 2 sentences — you are speaking aloud."
)


class LocalSession:
    """
    Manages one local conversation session (no cloud API).

    Mirrors GeminiLiveClient interface:  run_session(...) and close()
    """

    def __init__(self) -> None:
        self._running = False
        self._vosk_model = None      # loaded lazily
        self._vosk_rec = None
        self._vad = None             # loaded lazily

    def _get_vad(self):
        if self._vad is None:
            self._vad = create_vad(settings.VAD_BACKEND)
            logger.info("VAD loaded: %s", self._vad)
        return self._vad

    # ── Public API (same signature as GeminiLiveClient) ───────────────

    async def run_session(
        self,
        trigger_data: dict[str, Any],
        person_name: str | None = None,
        person_profile: dict | None = None,
    ) -> None:
        from jarvis.audio.tts import tts

        self._running = True
        source = trigger_data.get("source", "unknown")
        logger.info("Local session started (source=%s, mode=LOCAL/OFFLINE)", source)

        # Build a contextual greeting
        if person_name:
            greeting = f"Hello {person_name}! I'm running in offline mode. How can I help?"
        else:
            greeting = "I'm running in offline mode. How can I help you?"

        await event_bus.publish("session.state_changed", {"state": "LISTENING"})
        await tts.speak(greeting)

        for turn in range(settings.OFFLINE_MAX_TURNS):
            if not self._running:
                break

            # 1. Collect utterance
            await event_bus.publish("session.state_changed", {"state": "LISTENING"})
            logger.debug("Local session: listening (turn %d/%d)", turn + 1, settings.OFFLINE_MAX_TURNS)
            pcm_bytes = await self._collect_utterance()

            if not pcm_bytes:
                logger.debug("No speech detected — ending local session")
                break

            # 2. STT
            await event_bus.publish("session.state_changed", {"state": "PROCESSING"})
            text = await self._transcribe(pcm_bytes)
            if not text.strip():
                logger.debug("STT returned empty — skipping turn")
                continue

            logger.info("Local STT: %r", text)

            # 3. LLM
            system = _SYSTEM_PROMPT
            if person_name:
                system += f" You are speaking with {person_name}."
            response = await self._generate(text, system)
            logger.info("Local response: %r", response[:120])

            # 4. TTS
            await event_bus.publish("session.state_changed", {"state": "RESPONDING"})
            await tts.speak(response)

        await event_bus.publish("session.state_changed", {"state": "LISTENING"})
        logger.info("Local session ended after %d turn(s)", turn + 1)

    async def close(self) -> None:
        self._running = False

    # ── VAD — collect one utterance ───────────────────────────────────

    async def _collect_utterance(self) -> bytes:
        """
        Subscribe to audio_capture, collect chunks until silence or timeout.
        Returns raw int16 16kHz PCM bytes, or b'' if nothing captured.
        """
        from jarvis.audio.capture import audio_capture

        loop = asyncio.get_running_loop()
        chunk_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=500)

        def _on_chunk(chunk: np.ndarray) -> None:
            def _put() -> None:
                try:
                    chunk_queue.put_nowait(chunk.tobytes())
                except asyncio.QueueFull:
                    pass
            try:
                loop.call_soon_threadsafe(_put)
            except RuntimeError:
                pass

        audio_capture.add_subscriber(_on_chunk)

        vad = self._get_vad()
        vad.reset()

        collected: list[bytes] = []
        silence_count = 0
        speech_count = 0
        max_chunks = int(settings.OFFLINE_MAX_UTTERANCE_S * settings.AUDIO_TARGET_RATE /
                         (settings.AUDIO_CHUNK_SIZE // 3))  # approx chunks per second

        try:
            deadline = time.monotonic() + settings.OFFLINE_MAX_UTTERANCE_S + 5
            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(chunk_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if speech_count > 0:
                        silence_count += 3  # treat timeout as silence
                    continue

                samples = np.frombuffer(raw, dtype=np.int16)

                if vad.is_speech(samples):
                    collected.append(raw)
                    speech_count += 1
                    silence_count = 0
                elif speech_count > 0:
                    # In post-speech silence — keep collecting until gap large enough
                    collected.append(raw)
                    silence_count += 1
                    if silence_count >= _SILENCE_CHUNKS:
                        break  # natural end of utterance

                if len(collected) >= max_chunks:
                    logger.debug("Max utterance length reached")
                    break

        finally:
            audio_capture.remove_subscriber(_on_chunk)

        if speech_count < _MIN_SPEECH_CHUNKS:
            return b""  # too short — probably noise

        return b"".join(collected)

    # ── STT ───────────────────────────────────────────────────────────

    async def _transcribe(self, pcm_bytes: bytes) -> str:
        """Convert raw 16kHz int16 PCM to text using Vosk."""
        if not settings.OFFLINE_STT_ENABLED:
            return ""

        model_path = Path(settings.OFFLINE_STT_MODEL)
        if not model_path.exists():
            logger.warning(
                "Vosk model not found at %s — run make install or set OFFLINE_STT_MODEL",
                model_path,
            )
            return ""

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._vosk_transcribe, pcm_bytes)

    def _vosk_transcribe(self, pcm_bytes: bytes) -> str:
        """Blocking Vosk transcription (runs in thread pool)."""
        try:
            from vosk import KaldiRecognizer, Model

            if self._vosk_model is None:
                logger.info("Loading Vosk model from %s", settings.OFFLINE_STT_MODEL)
                self._vosk_model = Model(settings.OFFLINE_STT_MODEL)
                self._vosk_rec = KaldiRecognizer(self._vosk_model, settings.AUDIO_TARGET_RATE)

            self._vosk_rec.AcceptWaveform(pcm_bytes)
            result = json.loads(self._vosk_rec.FinalResult())
            return result.get("text", "")

        except ImportError:
            logger.warning("vosk not installed — pip install vosk")
            return ""
        except Exception:
            logger.exception("Vosk transcription error")
            return ""

    # ── LLM ───────────────────────────────────────────────────────────

    async def _generate(self, text: str, system: str) -> str:
        """Generate a response via Ollama (server or local)."""
        try:
            from jarvis.ai.ollama_fallback import ollama_fallback
            response = await ollama_fallback.generate(text, system=system)
            if response.strip():
                return response
        except Exception:
            logger.exception("Ollama generation error")

        return "I'm sorry, my local AI isn't available right now. Please check that Ollama is installed."
