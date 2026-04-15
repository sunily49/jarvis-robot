"""
ServerClient — manages Pi ↔ Home Server communication.

Features:
- WebSocket for vision frame streaming
- REST for Ollama LLM queries
- Health check polling every N seconds
- Auto-reconnect with exponential backoff
- `server_available` flag for graceful degradation
"""

import asyncio
import io
import json
import logging
from typing import Any

import aiohttp
from jarvis.config import settings

logger = logging.getLogger(__name__)


class ServerClient:
    """Client for communicating with the JARVIS home server."""

    def __init__(self) -> None:
        self._server_available = False
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._health_task: asyncio.Task | None = None
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0

    @property
    def server_available(self) -> bool:
        return self._server_available

    @property
    def base_url(self) -> str:
        return f"http://{settings.SERVER_HOST}:{settings.SERVER_PORT}"

    @property
    def ws_url(self) -> str:
        return f"ws://{settings.SERVER_HOST}:{settings.SERVER_PORT}/vision"

    async def start(self) -> None:
        """Start the server client with health monitoring."""
        if not settings.SERVER_ENABLED:
            logger.info("Server integration disabled")
            return
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        self._health_task = asyncio.create_task(self._health_loop())
        logger.info("ServerClient started, monitoring %s", self.base_url)

    async def stop(self) -> None:
        """Shut down the server client."""
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        await self._close_ws()
        if self._session:
            await self._session.close()
            self._session = None
        self._server_available = False
        logger.info("ServerClient stopped")

    # ── Health Check ──────────────────────────────────────────────────

    async def _health_loop(self) -> None:
        """Poll server health endpoint at regular intervals."""
        while True:
            try:
                await self._check_health()
                await asyncio.sleep(settings.SERVER_HEALTH_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Health check failed")
                self._server_available = False
                await asyncio.sleep(settings.SERVER_HEALTH_INTERVAL)

    async def _check_health(self) -> None:
        if not self._session:
            return
        try:
            async with self._session.get(f"{self.base_url}/health") as resp:
                if resp.status == 200:
                    if not self._server_available:
                        logger.info("Server came online: %s", self.base_url)
                        from jarvis.core.event_bus import event_bus
                        await event_bus.publish("server.online", {})
                    self._server_available = True
                    self._reconnect_delay = 1.0
                else:
                    self._server_available = False
        except (aiohttp.ClientError, asyncio.TimeoutError):
            if self._server_available:
                logger.warning("Server went offline: %s", self.base_url)
                from jarvis.core.event_bus import event_bus
                await event_bus.publish("server.offline", {})
            self._server_available = False

    # ── Vision WebSocket ──────────────────────────────────────────────

    async def _ensure_ws(self) -> aiohttp.ClientWebSocketResponse | None:
        """Ensure WebSocket connection is alive, reconnect if needed."""
        if self._ws and not self._ws.closed:
            return self._ws
        if not self._server_available or not self._session:
            return None
        try:
            self._ws = await self._session.ws_connect(self.ws_url)
            logger.info("Vision WebSocket connected")
            return self._ws
        except Exception:
            logger.debug("Vision WebSocket connection failed")
            return None

    async def _close_ws(self) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None

    async def send_frame(self, jpeg_bytes: bytes) -> dict[str, Any] | None:
        """Send a JPEG frame to server for vision processing. Returns detections."""
        ws = await self._ensure_ws()
        if not ws:
            return None
        try:
            await ws.send_bytes(jpeg_bytes)
            msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
            if msg.type == aiohttp.WSMsgType.TEXT:
                return json.loads(msg.data)
            return None
        except (asyncio.TimeoutError, aiohttp.ClientError):
            logger.debug("Frame send failed, closing WebSocket")
            await self._close_ws()
            return None

    # ── REST: Ollama LLM ─────────────────────────────────────────────

    async def query_ollama(self, prompt: str, system: str = "") -> str | None:
        """Send a text prompt to server's Ollama endpoint."""
        if not self._server_available or not self._session:
            return None
        try:
            payload = {"prompt": prompt, "system": system}
            async with self._session.post(
                f"{self.base_url}/llm/generate",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result.get("response")
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            logger.debug("Ollama query failed")
            return None

    # ── REST: Face Recognition ────────────────────────────────────────

    async def identify_face(self, jpeg_bytes: bytes) -> dict[str, Any] | None:
        """Send a face crop to server for identification."""
        if not self._server_available or not self._session:
            return None
        try:
            data = aiohttp.FormData()
            data.add_field("image", io.BytesIO(jpeg_bytes), content_type="image/jpeg")
            async with self._session.post(
                f"{self.base_url}/vision/identify",
                data=data,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None

    # ── REST: Face Registration ────────────────────────────────────────

    async def register_face(self, name: str, jpeg_bytes: bytes) -> bool:
        """Register a face on the server."""
        if not self._server_available or not self._session:
            return False
        try:
            data = aiohttp.FormData()
            data.add_field("name", name)
            data.add_field("image", io.BytesIO(jpeg_bytes), content_type="image/jpeg")
            async with self._session.post(
                f"{self.base_url}/vision/register_face",
                data=data,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    # ── REST: Voice Enrollment ───────────────────────────────────────

    async def enroll_voice(self, name: str, audio_bytes: bytes) -> bool:
        """Enroll a speaker voice on the server. audio_bytes = raw 16kHz PCM16."""
        if not self._server_available or not self._session:
            return False
        try:
            data = aiohttp.FormData()
            data.add_field("name", name)
            data.add_field("audio", io.BytesIO(audio_bytes), content_type="application/octet-stream")
            async with self._session.post(
                f"{self.base_url}/voice/enroll",
                data=data,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    async def identify_voice(self, audio_bytes: bytes) -> dict[str, Any] | None:
        """Identify a speaker from audio on the server."""
        if not self._server_available or not self._session:
            return None
        try:
            data = aiohttp.FormData()
            data.add_field("audio", io.BytesIO(audio_bytes), content_type="application/octet-stream")
            async with self._session.post(
                f"{self.base_url}/voice/identify",
                data=data,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None

    # ── REST: Person Registry ────────────────────────────────────────

    async def get_person(self, name: str) -> dict[str, Any] | None:
        """Get person profile from server registry."""
        if not self._server_available or not self._session:
            return None
        try:
            async with self._session.get(
                f"{self.base_url}/person/{name}",
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None

    async def list_registered(self) -> list[dict] | None:
        """List all registered persons with face/voice modality flags."""
        if not self._server_available or not self._session:
            return None
        try:
            async with self._session.get(f"{self.base_url}/persons/registered") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("persons", [])
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None

    async def rename_person(self, old_name: str, new_name: str) -> dict | None:
        """Rename a person across all server stores. Returns result dict or None."""
        if not self._server_available or not self._session:
            return None
        try:
            async with self._session.post(
                f"{self.base_url}/person/{old_name}/rename",
                json={"new_name": new_name},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None

    async def record_encounter(self, name: str) -> None:
        """Record that a person was seen."""
        if not self._server_available or not self._session:
            return
        try:
            await self._session.post(f"{self.base_url}/person/{name}/encounter")
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass

    # ── REST: YOLO Detection ─────────────────────────────────────────

    async def detect_objects(self, jpeg_bytes: bytes) -> list[dict[str, Any]] | None:
        """Send frame for YOLOv8 object detection."""
        if not self._server_available or not self._session:
            return None
        try:
            data = aiohttp.FormData()
            data.add_field("image", io.BytesIO(jpeg_bytes), content_type="image/jpeg")
            async with self._session.post(
                f"{self.base_url}/vision/detect",
                data=data,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result.get("detections", [])
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None


# Singleton instance
server_client = ServerClient()
