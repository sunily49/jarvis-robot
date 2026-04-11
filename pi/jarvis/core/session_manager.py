"""
SessionManager — manages Gemini Live session lifecycle.

States: IDLE → LISTENING → PROCESSING → RESPONDING → IDLE
Handles session start/stop, timeout, and graceful teardown.
"""

import asyncio
import logging
from enum import Enum, auto
from typing import Any

from jarvis.core.event_bus import event_bus

logger = logging.getLogger(__name__)


class SessionState(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    RESPONDING = auto()
    ERROR = auto()


class SessionManager:
    """Manages the lifecycle of a single Gemini Live conversation session."""

    def __init__(self) -> None:
        self._state = SessionState.IDLE
        self._session_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._gemini_live = None  # Set during init
        self._active_session: Any = None
        self._session_timeout = 300  # 5 min inactivity timeout

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state not in (SessionState.IDLE, SessionState.ERROR)

    async def initialize(self) -> None:
        """Set up event subscriptions."""
        await event_bus.subscribe("trigger.*", self._on_trigger)
        logger.info("SessionManager initialized, listening for triggers")

    async def _on_trigger(self, event: str, data: dict[str, Any]) -> None:
        """Handle incoming trigger events."""
        async with self._lock:
            if self._state == SessionState.IDLE:
                logger.info("Trigger received (%s), starting session", data.get("source"))
                await self._start_session(data)
            else:
                logger.debug("Trigger ignored, session already %s", self._state.name)

    async def _start_session(self, trigger_data: dict[str, Any]) -> None:
        """Start a new Gemini Live session."""
        self._state = SessionState.LISTENING
        await event_bus.publish("session.started", {
            "trigger": trigger_data.get("source", "unknown"),
        })

        try:
            from jarvis.ai.gemini_live import GeminiLiveClient
            client = GeminiLiveClient()
            self._active_session = client

            self._session_task = asyncio.create_task(
                self._run_session(client, trigger_data)
            )
        except Exception:
            logger.exception("Failed to start Gemini Live session")
            self._state = SessionState.ERROR
            await self._attempt_fallback(trigger_data)

    async def _run_session(self, client: Any, trigger_data: dict[str, Any]) -> None:
        """Run the conversation session with timeout."""
        try:
            self._state = SessionState.PROCESSING
            await client.run_session(trigger_data)
        except asyncio.TimeoutError:
            logger.warning("Session timed out after %ds", self._session_timeout)
        except Exception:
            logger.exception("Session error")
            await self._attempt_fallback(trigger_data)
        finally:
            await self._end_session()

    async def _attempt_fallback(self, trigger_data: dict[str, Any]) -> None:
        """Try Ollama fallback when Gemini fails."""
        from jarvis.config import settings
        if not settings.AI_OLLAMA_FALLBACK:
            logger.warning("No fallback configured, returning to idle")
            return

        logger.info("Attempting Ollama fallback")
        try:
            from jarvis.core.server_client import server_client
            if server_client.server_available:
                await event_bus.publish("session.fallback", {"engine": "ollama_server"})
            else:
                await event_bus.publish("session.fallback", {"engine": "ollama_local"})
        except Exception:
            logger.exception("Fallback also failed")

    async def _end_session(self) -> None:
        """Clean up and return to idle."""
        if self._active_session:
            try:
                await self._active_session.close()
            except Exception:
                logger.exception("Error closing session")
            self._active_session = None
        self._state = SessionState.IDLE
        self._session_task = None
        await event_bus.publish("session.ended", {})
        logger.info("Session ended, returning to IDLE")

    async def force_stop(self) -> None:
        """Force-stop the current session."""
        async with self._lock:
            if self._session_task and not self._session_task.done():
                self._session_task.cancel()
                try:
                    await self._session_task
                except asyncio.CancelledError:
                    pass
            await self._end_session()

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        await self.force_stop()
        logger.info("SessionManager shut down")
