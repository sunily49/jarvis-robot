"""
Ollama LLM Fallback — used when Gemini API is unavailable.

Two modes:
1. Server Ollama (mistral-7b, fast) — via server REST API
2. Local Ollama (phi-3-mini, slow) — direct on Pi as last resort

Outputs text → Piper TTS for voice.
"""

import asyncio
import logging
import subprocess
from typing import Any

from jarvis.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are JARVIS, an AI robot assistant. Be concise and helpful. "
    "Keep responses short — you are speaking aloud."
)


class OllamaFallback:
    """Ollama LLM for offline/fallback text generation."""

    def __init__(self) -> None:
        self._server_model = "mistral"     # Fast on server
        self._local_model = "phi3:mini"    # Tiny for Pi

    async def generate(self, prompt: str, system: str = "") -> str:
        """Try server Ollama first, fall back to local."""
        system = system or SYSTEM_PROMPT

        # Try server first
        from jarvis.core.server_client import server_client
        if server_client.server_available:
            result = await server_client.query_ollama(prompt, system)
            if result:
                logger.info("Ollama response via server (%d chars)", len(result))
                return result

        # Fall back to local
        logger.info("Attempting local Ollama fallback")
        return await self._local_generate(prompt, system)

    async def _local_generate(self, prompt: str, system: str) -> str:
        """Run Ollama locally on Pi (slow but offline)."""
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                self._run_ollama_cli,
                prompt,
                system,
            )
            return result
        except Exception:
            logger.exception("Local Ollama failed")
            return "I'm sorry, I'm unable to process that right now. My AI services are offline."

    def _run_ollama_cli(self, prompt: str, system: str) -> str:
        """Blocking call to local ollama CLI."""
        try:
            cmd = [
                "ollama", "run", self._local_model,
                "--system", system,
                prompt,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            logger.error("Ollama CLI error: %s", result.stderr)
            return ""
        except FileNotFoundError:
            logger.error("Ollama not installed. Install: curl -fsSL https://ollama.ai/install.sh | sh")
            return ""
        except subprocess.TimeoutExpired:
            logger.error("Ollama timed out (60s)")
            return ""

    async def is_available(self) -> bool:
        """Check if any Ollama path is available."""
        from jarvis.core.server_client import server_client
        if server_client.server_available:
            return True
        # Check local
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False


# Singleton
ollama_fallback = OllamaFallback()
