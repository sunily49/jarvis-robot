"""
SessionManager — manages Gemini Live / local AI session lifecycle.

AI backend is chosen automatically based on network connectivity:

  FULL_CLOUD   (internet available) → GeminiLiveClient
    Audio+video → Google Gemini Live → audio response

  LOCAL_SERVER (WiFi, no internet, server or local Ollama) → LocalSession
    Mic → VAD → Vosk STT → Ollama (server or local) → Piper TTS

  OFFLINE      (no network) → LocalSession
    Mic → VAD → Vosk STT → local Ollama → Piper TTS
    Falls back to scripted response if Ollama not installed.

If the internet drops while a Gemini session is active, the session is
cleanly cancelled and a LocalSession is started in its place.

States: IDLE → LISTENING → PROCESSING → RESPONDING → IDLE
"""

import asyncio
import logging
import time
from enum import Enum, auto
from typing import Any

from jarvis.core.event_bus import event_bus

logger = logging.getLogger(__name__)

_FACE_CONTEXT_TTL  = 60.0   # seconds before face identification expires
_VOICE_CONTEXT_TTL = 60.0   # seconds before voice identification expires
_VOICE_ID_AUDIO_S  = 1.5    # seconds of audio to collect for voice ID at session start


class SessionState(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    RESPONDING = auto()
    ERROR = auto()


class SessionManager:
    """Manages the lifecycle of a single AI conversation session."""

    def __init__(self) -> None:
        self._state = SessionState.IDLE
        self._session_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._active_session: Any = None
        self._last_trigger_data: dict[str, Any] = {}

        # Person context — populated by face.identified / voice.identified events
        self._last_identified_name: str | None = None
        self._last_identified_at: float = 0.0
        self._last_voice_identified_name: str | None = None
        self._last_voice_identified_at: float = 0.0

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state not in (SessionState.IDLE, SessionState.ERROR)

    # ── Initialization ───────────────────────────────────────────────

    async def initialize(self) -> None:
        """Set up event subscriptions."""
        await event_bus.subscribe("trigger.*", self._on_trigger)
        await event_bus.subscribe("face.identified", self._on_face_identified)
        await event_bus.subscribe("voice.identified", self._on_voice_identified)
        await event_bus.subscribe("session.force_stop", self._on_force_stop)
        await event_bus.subscribe("network.mode_changed", self._on_network_mode_changed)
        logger.info("SessionManager initialized, listening for triggers")

    # ── State management ─────────────────────────────────────────────

    async def _set_state(self, new_state: SessionState) -> None:
        self._state = new_state
        await event_bus.publish("session.state_changed", {"state": new_state.name})
        logger.debug("Session state → %s", new_state.name)

    # ── Event handlers ───────────────────────────────────────────────

    async def _on_trigger(self, event: str, data: dict[str, Any]) -> None:
        async with self._lock:
            if self._state == SessionState.IDLE:
                logger.info("Trigger received (%s), starting session", data.get("source"))
                await self._start_session(data)
            else:
                logger.debug("Trigger ignored — session already %s", self._state.name)

    async def _on_face_identified(self, _event: str, data: dict[str, Any]) -> None:
        name = data.get("name")
        confidence = data.get("confidence", 0.0)
        if name and confidence >= 0.5:
            self._last_identified_name = name
            self._last_identified_at = time.time()
            logger.info("Face context cached: %s (conf=%.2f)", name, confidence)

    async def _on_voice_identified(self, _event: str, data: dict[str, Any]) -> None:
        name = data.get("name")
        confidence = data.get("confidence", 0.0)
        if name and confidence >= 0.5:
            self._last_voice_identified_name = name
            self._last_voice_identified_at = time.time()
            logger.info("Voice context cached: %s (conf=%.2f)", name, confidence)

    async def _on_force_stop(self, _event: str, _data: dict[str, Any]) -> None:
        await self.force_stop()

    async def _on_network_mode_changed(self, _event: str, data: dict[str, Any]) -> None:
        """
        Internet dropped while Gemini is running → cancel and switch to LocalSession.
        Internet restored while local session is running → let it finish; next
        trigger will pick up FULL_CLOUD automatically.
        """
        new_mode = data.get("mode", "")
        previous = data.get("previous", "")

        if previous == "FULL_CLOUD" and new_mode != "FULL_CLOUD":
            async with self._lock:
                if self._state not in (SessionState.IDLE, SessionState.ERROR):
                    logger.warning(
                        "Internet lost during Gemini session — switching to local AI"
                    )
                    from jarvis.audio.tts import tts
                    # Cancel current Gemini session
                    if self._session_task and not self._session_task.done():
                        self._session_task.cancel()
                        try:
                            await self._session_task
                        except (asyncio.CancelledError, Exception):
                            pass
                    await self._end_session()
                    # Announce the switch, then restart with local AI
                    await tts.speak("Internet connection lost. Switching to offline mode.")
                    await self._start_session(self._last_trigger_data)

    # ── AI backend selection ─────────────────────────────────────────

    def _select_backend(self) -> str:
        """Return 'gemini' or 'local' based on current network mode."""
        from jarvis.config import settings
        from jarvis.core.network_monitor import NetworkMode, network_monitor

        mode = network_monitor.mode
        logger.info("Network mode: %s", mode.name)

        if settings.AI_GEMINI_LIVE and mode == NetworkMode.FULL_CLOUD:
            return "gemini"
        if settings.AI_OLLAMA_FALLBACK:
            return "local"
        # No AI at all — still return local so we give an audible response
        return "local"

    # ── Session lifecycle ─────────────────────────────────────────────

    async def _start_session(self, trigger_data: dict[str, Any]) -> None:
        self._last_trigger_data = trigger_data
        await self._set_state(SessionState.LISTENING)
        await event_bus.publish("session.started", {
            "trigger": trigger_data.get("source", "unknown"),
        })

        person_name = self._get_person_context()
        if not person_name:
            person_name = await self._try_identify_by_voice()

        person_profile: dict | None = None
        if person_name:
            person_profile = await self._fetch_person_profile(person_name)

        backend = self._select_backend()

        try:
            if backend == "gemini":
                await self._start_gemini_session(trigger_data, person_name, person_profile)
            else:
                await self._start_local_session(trigger_data, person_name, person_profile)
        except Exception:
            logger.exception("Failed to start session")
            await self._set_state(SessionState.ERROR)
            await self._end_session()

    async def _start_gemini_session(
        self,
        trigger_data: dict[str, Any],
        person_name: str | None,
        person_profile: dict | None,
    ) -> None:
        from jarvis.ai.gemini_live import GeminiLiveClient
        from jarvis.tools.mcp_server import get_tool_schemas_dict

        client = GeminiLiveClient()
        tool_schemas = get_tool_schemas_dict()
        if tool_schemas:
            client.register_tools(tool_schemas)

        self._active_session = client
        self._session_task = asyncio.create_task(
            self._run_session(client, trigger_data, person_name, person_profile),
            name="gemini_session",
        )

    async def _start_local_session(
        self,
        trigger_data: dict[str, Any],
        person_name: str | None,
        person_profile: dict | None,
    ) -> None:
        from jarvis.ai.local_session import LocalSession

        client = LocalSession()
        self._active_session = client
        self._session_task = asyncio.create_task(
            self._run_session(client, trigger_data, person_name, person_profile),
            name="local_session",
        )

    async def _run_session(
        self,
        client: Any,
        trigger_data: dict[str, Any],
        person_name: str | None,
        person_profile: dict | None,
    ) -> None:
        try:
            await self._set_state(SessionState.PROCESSING)
            await client.run_session(
                trigger_data,
                person_name=person_name,
                person_profile=person_profile,
            )
        except asyncio.CancelledError:
            logger.info("Session cancelled")
        except Exception:
            logger.exception("Session error")
        finally:
            await self._end_session()

    async def _end_session(self) -> None:
        if self._active_session:
            try:
                await self._active_session.close()
            except Exception:
                pass
            self._active_session = None
        self._session_task = None
        await self._set_state(SessionState.IDLE)
        await event_bus.publish("session.ended", {})
        logger.info("Session ended → IDLE")

    # ── Person context ───────────────────────────────────────────────

    def _get_person_context(self) -> str | None:
        """Return the most recently identified person name within TTL. Face takes priority."""
        now = time.time()
        face_name = (
            self._last_identified_name
            if self._last_identified_name and now - self._last_identified_at <= _FACE_CONTEXT_TTL
            else None
        )
        voice_name = (
            self._last_voice_identified_name
            if self._last_voice_identified_name and now - self._last_voice_identified_at <= _VOICE_CONTEXT_TTL
            else None
        )
        return face_name or voice_name

    async def _try_identify_by_voice(self) -> str | None:
        """
        Collect _VOICE_ID_AUDIO_S seconds of mic audio and ask the server to identify
        the speaker. Called at session start when no face context is available.
        Returns the identified name, or None if identification fails or is below threshold.
        """
        try:
            from jarvis.core.server_client import server_client
            if not server_client.server_available:
                return None

            from jarvis.audio.capture import audio_capture

            chunks: list[bytes] = []

            def _collect(chunk) -> None:
                chunks.append(chunk if isinstance(chunk, bytes) else chunk.tobytes())

            audio_capture.add_subscriber(_collect)
            try:
                await asyncio.sleep(_VOICE_ID_AUDIO_S)
            finally:
                audio_capture.remove_subscriber(_collect)

            if not chunks:
                return None

            result = await asyncio.wait_for(
                server_client.identify_voice(b"".join(chunks)),
                timeout=2.0,
            )
            if result and result.get("name") and result.get("confidence", 0.0) >= 0.5:
                name = result["name"]
                confidence = float(result["confidence"])
                self._last_voice_identified_name = name
                self._last_voice_identified_at = time.time()
                await event_bus.publish("voice.identified", {"name": name, "confidence": confidence})
                logger.info("Voice identified at session start: %s (conf=%.2f)", name, confidence)
                return name

        except asyncio.TimeoutError:
            logger.debug("Voice identification timed out at session start")
        except Exception:
            logger.debug("Voice identification failed at session start", exc_info=True)
        return None

    async def _fetch_person_profile(self, name: str) -> dict | None:
        try:
            from jarvis.core.server_client import server_client
            if server_client.server_available:
                return await server_client.get_person(name)
        except Exception:
            pass
        try:
            from jarvis.memory.conversation_memory import conversation_memory
            return await conversation_memory.get_entity(name)
        except Exception:
            pass
        return None

    # ── Public control ───────────────────────────────────────────────

    async def force_stop(self) -> None:
        async with self._lock:
            if self._session_task and not self._session_task.done():
                self._session_task.cancel()
                try:
                    await self._session_task
                except (asyncio.CancelledError, Exception):
                    pass
            await self._end_session()

    async def shutdown(self) -> None:
        await self.force_stop()
        logger.info("SessionManager shut down")
