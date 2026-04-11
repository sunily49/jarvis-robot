"""
SessionManager — manages Gemini Live session lifecycle.

States: IDLE → LISTENING → PROCESSING → RESPONDING → IDLE

Publishes session.state_changed on every transition so the display,
event bus subscribers, and other modules always know the current state.

Person context: if a face was recently identified (within 60s), that
person's profile is fetched and injected into the Gemini system prompt.
"""

import asyncio
import logging
import time
from enum import Enum, auto
from typing import Any

from jarvis.core.event_bus import event_bus

logger = logging.getLogger(__name__)

_FACE_CONTEXT_TTL = 60.0  # seconds before face identification expires


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
        self._active_session: Any = None
        self._session_timeout = 300  # 5 min inactivity timeout

        # Person context — populated by face.identified events
        self._last_identified_name: str | None = None
        self._last_identified_at: float = 0.0
        self._last_identified_confidence: float = 0.0

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state not in (SessionState.IDLE, SessionState.ERROR)

    async def initialize(self) -> None:
        """Set up event subscriptions."""
        await event_bus.subscribe("trigger.*", self._on_trigger)
        await event_bus.subscribe("face.identified", self._on_face_identified)
        await event_bus.subscribe("session.force_stop", self._on_force_stop)
        logger.info("SessionManager initialized, listening for triggers")

    # ── State Management ─────────────────────────────────────────────

    async def _set_state(self, new_state: SessionState) -> None:
        """Set state and publish session.state_changed event for display/subscribers."""
        self._state = new_state
        await event_bus.publish("session.state_changed", {
            "state": new_state.name,
        })
        logger.debug("Session state → %s", new_state.name)

    # ── Event Handlers ───────────────────────────────────────────────

    async def _on_trigger(self, event: str, data: dict[str, Any]) -> None:
        """Handle incoming trigger events."""
        async with self._lock:
            if self._state == SessionState.IDLE:
                logger.info("Trigger received (%s), starting session", data.get("source"))
                await self._start_session(data)
            else:
                logger.debug("Trigger ignored — session already %s", self._state.name)

    async def _on_face_identified(self, _event: str, data: dict[str, Any]) -> None:
        """Cache the last identified person for context injection."""
        name = data.get("name")
        confidence = data.get("confidence", 0.0)
        if name and confidence >= 0.5:
            self._last_identified_name = name
            self._last_identified_at = time.time()
            self._last_identified_confidence = confidence
            logger.info("Person context cached: %s (conf=%.2f)", name, confidence)

    async def _on_force_stop(self, _event: str, _data: dict[str, Any]) -> None:
        await self.force_stop()

    # ── Person Context ───────────────────────────────────────────────

    def _get_person_context(self) -> str | None:
        """Return cached person context if still fresh."""
        if not self._last_identified_name:
            return None
        age = time.time() - self._last_identified_at
        if age > _FACE_CONTEXT_TTL:
            return None
        return self._last_identified_name

    async def _fetch_person_profile(self, name: str) -> dict | None:
        """Try to fetch full person profile from server registry."""
        try:
            from jarvis.core.server_client import server_client
            if server_client.server_available:
                return await server_client.get_person(name)
        except Exception:
            pass
        # Fallback: check local entity memory
        try:
            from jarvis.memory.conversation_memory import conversation_memory
            return await conversation_memory.get_entity(name)
        except Exception:
            pass
        return None

    # ── Session Lifecycle ────────────────────────────────────────────

    async def _start_session(self, trigger_data: dict[str, Any]) -> None:
        """Start a new Gemini Live session."""
        await self._set_state(SessionState.LISTENING)
        await event_bus.publish("session.started", {
            "trigger": trigger_data.get("source", "unknown"),
        })

        # Resolve person context
        person_name = self._get_person_context()
        person_profile: dict | None = None
        if person_name:
            person_profile = await self._fetch_person_profile(person_name)

        try:
            from jarvis.ai.gemini_live import GeminiLiveClient
            from jarvis.tools.mcp_server import get_tool_schemas_dict
            client = GeminiLiveClient()

            # Register all MCP tools for function calling
            tool_schemas = get_tool_schemas_dict()
            if tool_schemas:
                client.register_tools(tool_schemas)

            self._active_session = client
            self._session_task = asyncio.create_task(
                self._run_session(client, trigger_data, person_name, person_profile)
            )
        except Exception:
            logger.exception("Failed to start Gemini Live session")
            await self._set_state(SessionState.ERROR)
            await self._attempt_fallback(trigger_data)

    async def _run_session(
        self,
        client: Any,
        trigger_data: dict[str, Any],
        person_name: str | None,
        person_profile: dict | None,
    ) -> None:
        """Run the conversation session with timeout."""
        try:
            await self._set_state(SessionState.PROCESSING)
            await client.run_session(
                trigger_data,
                person_name=person_name,
                person_profile=person_profile,
            )
        except asyncio.TimeoutError:
            logger.warning("Session timed out after %ds", self._session_timeout)
        except asyncio.CancelledError:
            logger.info("Session cancelled")
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
            engine = "ollama_server" if server_client.server_available else "ollama_local"
            await event_bus.publish("session.fallback", {"engine": engine})
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
        self._session_task = None
        await self._set_state(SessionState.IDLE)
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
