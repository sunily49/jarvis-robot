"""
Gemini Live Client — native multimodal streaming (voice-in, voice-out).

This is the PRIMARY conversation path. Audio flows directly:
  Mic → 16kHz PCM → WebSocket → Gemini Live → audio chunks → Speaker

No local STT or TTS in this path.
Supports function calling for MCP tools.
"""

import asyncio
import base64
import json
import logging
from typing import Any

from jarvis.config import settings
from jarvis.core.event_bus import event_bus

logger = logging.getLogger(__name__)

# Gemini Live API constants
GEMINI_LIVE_MODEL = "gemini-2.0-flash-live"
GEMINI_WS_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"


class GeminiLiveClient:
    """Manages a single Gemini Live streaming session."""

    def __init__(self) -> None:
        self._ws = None
        self._running = False
        self._audio_task: asyncio.Task | None = None
        self._camera_task: asyncio.Task | None = None
        self._receive_task: asyncio.Task | None = None
        self._tool_registry: dict[str, Any] = {}
        self._person_name: str | None = None
        self._person_profile: dict | None = None

    def register_tools(self, tools: dict[str, Any]) -> None:
        """Register MCP tools for function calling."""
        self._tool_registry.update(tools)

    async def run_session(
        self,
        trigger_data: dict[str, Any],
        person_name: str | None = None,
        person_profile: dict | None = None,
    ) -> None:
        """Run a full Gemini Live conversation session."""
        import websockets

        self._person_name = person_name
        self._person_profile = person_profile

        url = f"{GEMINI_WS_URL}?key={settings.GEMINI_API_KEY}"

        try:
            async with websockets.connect(url) as ws:
                self._ws = ws
                self._running = True

                # Send setup message
                await self._send_setup(trigger_data)

                # Start concurrent tasks: audio in, camera in, responses out
                self._audio_task = asyncio.create_task(self._send_audio_loop())
                self._receive_task = asyncio.create_task(self._receive_loop())

                # Camera streaming — only if camera is enabled
                if settings.TOOL_CAMERA_PTZ or settings.TRIGGER_FACE:
                    self._camera_task = asyncio.create_task(self._send_camera_loop())

                tasks = [self._audio_task, self._receive_task]
                if self._camera_task:
                    tasks.append(self._camera_task)

                # Wait for session to end (any task finishing ends the session)
                await asyncio.gather(*tasks)

        except Exception:
            logger.exception("Gemini Live session error")
            raise
        finally:
            self._running = False

    async def _send_setup(self, trigger_data: dict[str, Any]) -> None:
        """Send initial setup message with system prompt and tool declarations."""
        # Build system context
        system_parts = [
            "You are JARVIS, an intelligent robot assistant running on a Raspberry Pi 5.",
            "You can see through a camera, hear through a microphone, and interact with your environment.",
            "Be concise, helpful, and natural in conversation.",
        ]

        # Add memory context if available
        try:
            from jarvis.memory.conversation_memory import conversation_memory
            recent = await conversation_memory.get_recent_context()
            if recent:
                system_parts.append(f"Recent conversation context:\n{recent}")
        except Exception:
            pass

        # Inject identified person context
        if self._person_name:
            system_parts.append(f"You are currently speaking with {self._person_name}.")
            if self._person_profile:
                prefs = self._person_profile.get("preferences", {})
                notes = self._person_profile.get("notes", "")
                encounters = self._person_profile.get("encounter_count", 0)
                if encounters == 1:
                    system_parts.append(f"This is your first time meeting {self._person_name}.")
                else:
                    system_parts.append(f"You have met {self._person_name} {encounters} times before.")
                if prefs.get("greeting"):
                    system_parts.append(f"Preferred greeting for {self._person_name}: {prefs['greeting']}")
                if notes:
                    system_parts.append(f"Notes about {self._person_name}: {notes}")

        setup_msg = {
            "setup": {
                "model": f"models/{GEMINI_LIVE_MODEL}",
                "generation_config": {
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                        "voice_config": {
                            "prebuilt_voice_config": {
                                "voice_name": "Aoede"
                            }
                        }
                    }
                },
                "system_instruction": {
                    "parts": [{"text": "\n".join(system_parts)}]
                },
            }
        }

        # Add tool declarations if any
        if self._tool_registry:
            setup_msg["setup"]["tools"] = [
                {"function_declarations": list(self._tool_registry.values())}
            ]

        await self._ws.send(json.dumps(setup_msg))
        # Wait for setup complete
        response = await self._ws.recv()
        data = json.loads(response)
        if "setupComplete" in data:
            logger.info("Gemini Live session established")
        else:
            logger.warning("Unexpected setup response: %s", data)

    async def _send_audio_loop(self) -> None:
        """Stream microphone audio to Gemini Live."""
        from jarvis.audio.capture import audio_capture

        while self._running:
            try:
                raw_bytes = audio_capture.get_raw_bytes(n_chunks=2)
                if raw_bytes:
                    msg = {
                        "realtime_input": {
                            "media_chunks": [{
                                "data": base64.b64encode(raw_bytes).decode("utf-8"),
                                "mime_type": "audio/pcm;rate=16000",
                            }]
                        }
                    }
                    await self._ws.send(json.dumps(msg))
                await asyncio.sleep(0.1)  # ~10 chunks/second
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Audio send error")
                break

    async def _send_camera_loop(self) -> None:
        """Continuously stream camera frames to Gemini Live for visual context.

        Sends 1 frame every 2 seconds — enough for scene awareness without
        saturating the WebSocket. Gemini can describe what it sees, detect
        objects/people, and answer "what do you see?" in real time.
        """
        try:
            from jarvis.vision.camera_controller import camera_controller
        except Exception:
            logger.warning("Camera controller unavailable — no visual feed to Gemini")
            return

        logger.info("Camera streaming to Gemini Live started (1 fps)")

        while self._running:
            try:
                jpeg_bytes = await camera_controller.capture_frame()
                if jpeg_bytes and self._ws and self._running:
                    msg = {
                        "realtime_input": {
                            "media_chunks": [{
                                "data": base64.b64encode(jpeg_bytes).decode("utf-8"),
                                "mime_type": "image/jpeg",
                            }]
                        }
                    }
                    await self._ws.send(json.dumps(msg))

                # 1 frame per 2 seconds — balances visual awareness vs bandwidth
                await asyncio.sleep(2.0)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Camera frame send failed — skipping frame")
                await asyncio.sleep(2.0)

        logger.info("Camera streaming to Gemini Live stopped")

    async def _receive_loop(self) -> None:
        """Receive and process Gemini Live responses."""
        from jarvis.audio.playback import audio_playback

        while self._running:
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=30.0)
                data = json.loads(raw)

                response = data.get("serverContent") or data.get("toolCall")

                if "serverContent" in data:
                    content = data["serverContent"]
                    if content.get("turnComplete"):
                        logger.debug("Gemini turn complete")
                        continue

                    parts = content.get("modelTurn", {}).get("parts", [])
                    for part in parts:
                        # Audio response — signal RESPONDING state on first chunk
                        if "inlineData" in part:
                            audio_b64 = part["inlineData"]["data"]
                            audio_bytes = base64.b64decode(audio_b64)
                            await audio_playback.play_gemini_chunk(audio_bytes, sample_rate=24000)
                            await event_bus.publish("session.state_changed", {"state": "RESPONDING"})

                        # Text response — log, memory, display transcript
                        if "text" in part:
                            text = part["text"]
                            logger.info("Gemini text: %s", text[:100])
                            await event_bus.publish("gemini.text", {"text": text})
                            await event_bus.publish("session.transcript", {
                                "role": "assistant",
                                "text": text,
                            })
                            # Save to conversation memory
                            try:
                                from jarvis.memory.conversation_memory import conversation_memory
                                await conversation_memory.append_exchange(
                                    role="assistant",
                                    content=text,
                                    metadata={"person": self._person_name},
                                )
                            except Exception:
                                pass

                    if content.get("turnComplete"):
                        # Back to PROCESSING (listening for user input)
                        await event_bus.publish("session.state_changed", {"state": "PROCESSING"})

                elif "toolCall" in data:
                    await self._handle_tool_call(data["toolCall"])

                # User speech detected — publish transcript placeholder
                elif "inputTranscript" in data:
                    text = data["inputTranscript"].get("text", "")
                    if text:
                        await event_bus.publish("session.transcript", {
                            "role": "user",
                            "text": text,
                        })
                        await event_bus.publish("session.state_changed", {"state": "PROCESSING"})
                        try:
                            from jarvis.memory.conversation_memory import conversation_memory
                            await conversation_memory.append_exchange(
                                role="user",
                                content=text,
                                metadata={"person": self._person_name},
                            )
                        except Exception:
                            pass

            except asyncio.TimeoutError:
                logger.info("Session timeout — no activity for 30s")
                break
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Receive error")
                break

    async def _handle_tool_call(self, tool_call: dict) -> None:
        """Execute a tool call from Gemini and send back the result."""
        function_calls = tool_call.get("functionCalls", [])
        responses = []

        for fc in function_calls:
            name = fc["name"]
            args = fc.get("args", {})
            logger.info("Tool call: %s(%s)", name, args)

            try:
                from jarvis.tools.mcp_server import execute_tool
                result = await execute_tool(name, args)
                responses.append({
                    "name": name,
                    "response": {"result": result},
                })
            except Exception as e:
                logger.exception("Tool %s failed", name)
                responses.append({
                    "name": name,
                    "response": {"error": str(e)},
                })

        # Send tool responses back to Gemini
        msg = {
            "toolResponse": {
                "functionResponses": responses
            }
        }
        await self._ws.send(json.dumps(msg))

    async def send_frame(self, jpeg_bytes: bytes) -> None:
        """Send a camera frame to Gemini for vision analysis during session."""
        if not self._ws or not self._running:
            return
        msg = {
            "realtime_input": {
                "media_chunks": [{
                    "data": base64.b64encode(jpeg_bytes).decode("utf-8"),
                    "mime_type": "image/jpeg",
                }]
            }
        }
        await self._ws.send(json.dumps(msg))

    async def close(self) -> None:
        """Close the session."""
        self._running = False
        for task in (self._audio_task, self._camera_task, self._receive_task):
            if task:
                task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        logger.info("Gemini Live client closed")
