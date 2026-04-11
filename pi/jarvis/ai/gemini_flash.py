"""
Gemini Flash — single-turn text/vision queries.

Used for non-conversational tasks: scene description, object analysis,
text-based queries. Returns text (use Piper TTS for voice output).
"""

import base64
import logging
from typing import Any

import google.generativeai as genai

from jarvis.config import settings

logger = logging.getLogger(__name__)

FLASH_MODEL = "gemini-2.0-flash"


class GeminiFlash:
    """Single-turn Gemini Flash for text and vision queries."""

    def __init__(self) -> None:
        self._model = None

    def _ensure_model(self) -> None:
        if self._model is None:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self._model = genai.GenerativeModel(FLASH_MODEL)

    async def query_text(self, prompt: str, system: str = "") -> str:
        """Send a text-only query."""
        self._ensure_model()
        try:
            config = {}
            if system:
                config["system_instruction"] = system
            response = await self._model.generate_content_async(
                prompt,
                generation_config=config,
            )
            return response.text
        except Exception:
            logger.exception("Gemini Flash text query failed")
            return ""

    async def query_vision(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> str:
        """Send an image + text query for visual analysis."""
        self._ensure_model()
        try:
            image_part = {
                "mime_type": mime_type,
                "data": image_bytes,
            }
            response = await self._model.generate_content_async(
                [prompt, image_part],
            )
            return response.text
        except Exception:
            logger.exception("Gemini Flash vision query failed")
            return ""

    async def describe_scene(self, jpeg_bytes: bytes) -> str:
        """Describe what the camera sees."""
        return await self.query_vision(
            "Describe what you see in this image concisely. "
            "Mention people, objects, and any notable activity.",
            jpeg_bytes,
        )

    async def analyze_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Query with function calling support. Returns tool calls or text."""
        self._ensure_model()
        try:
            response = await self._model.generate_content_async(
                prompt,
                tools=tools,
            )
            # Check for function calls
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        return {
                            "type": "function_call",
                            "name": part.function_call.name,
                            "args": dict(part.function_call.args),
                        }
            return {"type": "text", "text": response.text}
        except Exception:
            logger.exception("Gemini Flash tool query failed")
            return {"type": "error", "text": ""}


# Singleton
gemini_flash = GeminiFlash()
