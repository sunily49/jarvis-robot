"""
Ollama LLM Service — mistral-7b (or configurable) via Ollama API.
"""

import logging
import os
import subprocess

import requests

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral")


class OllamaService:
    def __init__(self) -> None:
        self._model = OLLAMA_MODEL
        logger.info("Ollama service initialized (model=%s, host=%s)", self._model, OLLAMA_HOST)

    def generate(self, prompt: str, system: str = "") -> str:
        """Generate a response using Ollama REST API."""
        try:
            payload = {
                "model": self._model,
                "prompt": prompt,
                "stream": False,
            }
            if system:
                payload["system"] = system

            resp = requests.post(
                f"{OLLAMA_HOST}/api/generate",
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        except requests.ConnectionError:
            logger.error("Cannot connect to Ollama at %s — is it running?", OLLAMA_HOST)
            return ""
        except requests.Timeout:
            logger.error("Ollama request timed out")
            return ""
        except Exception:
            logger.exception("Ollama generate error")
            return ""

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False
