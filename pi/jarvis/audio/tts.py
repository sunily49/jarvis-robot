"""
Piper TTS — local text-to-speech for system announcements and fallback.

NOT used for primary Gemini Live conversation (which has native audio output).
Used for: system announcements, Ollama responses, Gemini Flash text responses.
"""

import asyncio
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from jarvis.audio.playback import PlaybackPriority, audio_playback
from jarvis.config import settings

logger = logging.getLogger(__name__)


class PiperTTS:
    """Piper TTS wrapper — converts text to speech via subprocess."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")
        self._model_path = Path(settings.PIPER_MODEL_PATH)
        self._config_path = Path(settings.PIPER_CONFIG_PATH)

    async def speak(
        self,
        text: str,
        priority: PlaybackPriority = PlaybackPriority.SYSTEM,
    ) -> None:
        """Convert text to speech and play it."""
        if not text.strip():
            return
        loop = asyncio.get_event_loop()
        audio_data = await loop.run_in_executor(self._executor, self._synthesize, text)
        if audio_data:
            await audio_playback.play(audio_data, sample_rate=22050, priority=priority)

    def _synthesize(self, text: str) -> bytes | None:
        """Run Piper TTS subprocess to generate raw PCM audio."""
        try:
            cmd = [
                "piper",
                "--model", str(self._model_path),
                "--config", str(self._config_path),
                "--output-raw",
            ]
            result = subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0:
                return result.stdout
            logger.error("Piper TTS failed: %s", result.stderr.decode())
            return None
        except FileNotFoundError:
            logger.error("Piper not found in PATH. Install: pip install piper-tts")
            return None
        except subprocess.TimeoutExpired:
            logger.error("Piper TTS timed out")
            return None

    async def announce(self, text: str) -> None:
        """Convenience method for system announcements."""
        logger.info("Announcement: %s", text)
        await self.speak(text, priority=PlaybackPriority.SYSTEM)

    async def alert(self, text: str) -> None:
        """High-priority alert announcement."""
        logger.warning("Alert: %s", text)
        await self.speak(text, priority=PlaybackPriority.ALERT)


# Singleton
tts = PiperTTS()
