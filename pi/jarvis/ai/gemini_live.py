"""
Gemini Live Client — native multimodal streaming (voice-in, voice-out).

Uses google-genai SDK (same as working standalone script).
Audio flows directly: Mic → 16kHz PCM → Gemini Live → audio chunks → Speaker
Supports function calling for MCP tools.
"""

import asyncio
import base64
import logging
from typing import Any

from jarvis.config import settings
from jarvis.core.event_bus import event_bus

logger = logging.getLogger(__name__)

GEMINI_LIVE_MODEL = "gemini-2.0-flash-live-preview"


class GeminiLiveClient:
    """Manages a single Gemini Live streaming session using google-genai SDK."""

    def __init__(self) -> None:
        self._running = False
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
        from google import genai
        from google.genai import types

        self._person_name = person_name
        self._person_profile = person_profile
        self._running = True

        client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options={"api_version": "v1beta"},
        )

        # Build system prompt
        system_parts = [
            "You are JARVIS, an intelligent robot assistant running on a Raspberry Pi 5.",
            "You can see through a camera, hear through a microphone, and interact with your environment.",
            "Be concise, helpful, and natural in conversation.",
            "Keep responses under 3 sentences unless detail is needed.",
        ]

        try:
            from jarvis.memory.conversation_memory import conversation_memory
            recent = await conversation_memory.get_recent_context()
            if recent:
                system_parts.append(f"Recent conversation context:\n{recent}")
        except Exception:
            pass

        if self._person_name:
            system_parts.append(f"You are currently speaking with {self._person_name}.")
            if self._person_profile:
                encounters = self._person_profile.get("encounter_count", 0)
                if encounters == 1:
                    system_parts.append(f"This is your first time meeting {self._person_name}.")
                else:
                    system_parts.append(f"You have met {self._person_name} {encounters} times before.")

        live_config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction="\n".join(system_parts),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                )
            ),
        )

        try:
            async with client.aio.live.connect(
                model=GEMINI_LIVE_MODEL,
                config=live_config,
            ) as session:
                logger.info("Gemini Live session established (model=%s)", GEMINI_LIVE_MODEL)
                await event_bus.publish("session.state_changed", {"state": "LISTENING"})

                loop = asyncio.get_running_loop()
                active = True
                speaking = False

                async def send_mic() -> None:
                    nonlocal active
                    from jarvis.audio.capture import audio_capture
                    try:
                        while active:
                            raw_bytes = audio_capture.get_raw_bytes(n_chunks=2)
                            if raw_bytes:
                                if not speaking:
                                    await session.send_realtime_input(
                                        audio=types.Blob(
                                            data=raw_bytes,
                                            mime_type="audio/pcm;rate=16000",
                                        )
                                    )
                            await asyncio.sleep(0.06)
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        logger.exception("Mic send error")
                        active = False

                async def send_camera() -> None:
                    nonlocal active
                    try:
                        from jarvis.vision.camera_controller import camera_controller
                        while active:
                            jpeg = await camera_controller.capture_frame()
                            if jpeg and active:
                                await session.send_realtime_input(
                                    video=types.Blob(data=jpeg, mime_type="image/jpeg")
                                )
                            await asyncio.sleep(5.0)
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        logger.debug("Camera send error — skipping visual feed")

                async def recv_speaker() -> None:
                    nonlocal active, speaking
                    from jarvis.audio.playback import audio_playback
                    try:
                        while active:
                            async for msg in session.receive():
                                sc = msg.server_content

                                # Audio response
                                pcm_bytes = None
                                if getattr(msg, "data", None):
                                    pcm_bytes = msg.data
                                elif sc and getattr(sc, "model_turn", None):
                                    for part in sc.model_turn.parts:
                                        if getattr(part, "inline_data", None) and part.inline_data.data:
                                            pcm_bytes = part.inline_data.data
                                            break

                                if pcm_bytes:
                                    speaking = True
                                    await audio_playback.play_gemini_chunk(pcm_bytes, sample_rate=24000)
                                    await event_bus.publish("session.state_changed", {"state": "RESPONDING"})

                                if sc and getattr(sc, "interrupted", False):
                                    speaking = False
                                    logger.debug("User interrupted Gemini")

                                if sc and getattr(sc, "turn_complete", False):
                                    await asyncio.sleep(0.3)
                                    speaking = False
                                    await event_bus.publish("session.state_changed", {"state": "LISTENING"})
                                    logger.debug("Gemini turn complete — listening")

                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        logger.exception("Receive error")
                        active = False

                tasks = [
                    asyncio.create_task(send_mic()),
                    asyncio.create_task(recv_speaker()),
                    asyncio.create_task(send_camera()),
                ]

                try:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=180,
                    )
                except asyncio.TimeoutError:
                    logger.info("Gemini Live session timeout (180s)")
                finally:
                    active = False
                    for t in tasks:
                        t.cancel()

        except Exception:
            logger.exception("Gemini Live session error")
            raise
        finally:
            self._running = False

    async def close(self) -> None:
        """Close the session."""
        self._running = False
        logger.info("Gemini Live client closed")
