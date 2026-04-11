"""
MCP Person Tools — Gemini can register/identify faces and voices,
and manage person profiles.

Registration flow:
1. Face: "Remember this person" → capture frame → send to server → register
2. Voice: "Learn my voice" → record 5s audio → send to server → enroll
3. Both feed into a unified person registry on the server
"""

import asyncio
import logging

from jarvis.tools.mcp_server import mcp_tool

logger = logging.getLogger(__name__)


@mcp_tool(
    name="register_person_face",
    description="Register a person's face so the robot can recognize them later. Takes a photo and associates it with the given name. Ask the person to look at the camera.",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The person's name to associate with their face.",
            },
        },
        "required": ["name"],
    },
)
async def register_person_face(name: str) -> dict:
    from jarvis.core.server_client import server_client
    from jarvis.vision.camera_controller import camera_controller

    if not server_client.server_available:
        return {"status": "error", "message": "Server offline — face registration requires server"}

    frame = await camera_controller.capture_frame()
    if not frame:
        return {"status": "error", "message": "Could not capture camera frame"}

    ok = await server_client.register_face(name, frame)
    if ok:
        logger.info("Registered face: %s", name)
        return {"status": "ok", "message": f"I've learned {name}'s face. I'll recognize them next time."}
    return {"status": "error", "message": "No face detected in camera frame. Ask the person to face the camera."}


@mcp_tool(
    name="register_person_voice",
    description="Record and register a person's voice so the robot can identify them by speech. Records 5 seconds of audio. Ask the person to speak clearly.",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The person's name to associate with their voice.",
            },
        },
        "required": ["name"],
    },
)
async def register_person_voice(name: str) -> dict:
    from jarvis.core.server_client import server_client
    from jarvis.audio.capture import audio_capture

    if not server_client.server_available:
        return {"status": "error", "message": "Server offline — voice enrollment requires server"}

    # Record 5 seconds of audio for enrollment
    chunks = []
    duration = 5.0
    collected = 0.0
    chunk_duration = 1024 / 16000  # ~64ms per chunk at 16kHz

    def collector(chunk: bytes) -> None:
        chunks.append(chunk)

    audio_capture.add_subscriber(collector)
    try:
        await asyncio.sleep(duration)
    finally:
        audio_capture.remove_subscriber(collector)

    if not chunks:
        return {"status": "error", "message": "No audio captured"}

    audio_bytes = b"".join(chunks)
    ok = await server_client.enroll_voice(name, audio_bytes)
    if ok:
        logger.info("Enrolled voice: %s", name)
        return {"status": "ok", "message": f"I've learned {name}'s voice. I can identify them by speech now."}
    return {"status": "error", "message": "Audio too short or unclear. Ask the person to speak for at least 3 seconds."}


@mcp_tool(
    name="identify_current_speaker",
    description="Try to identify who is currently speaking by their voice. Records a short audio sample and checks against known voices.",
    parameters={"type": "object", "properties": {}},
)
async def identify_current_speaker() -> dict:
    from jarvis.core.server_client import server_client
    from jarvis.audio.capture import audio_capture

    if not server_client.server_available:
        return {"status": "error", "message": "Server offline — voice identification requires server"}

    chunks = []

    def collector(chunk: bytes) -> None:
        chunks.append(chunk)

    audio_capture.add_subscriber(collector)
    try:
        await asyncio.sleep(3.0)
    finally:
        audio_capture.remove_subscriber(collector)

    if not chunks:
        return {"name": None, "confidence": 0.0, "message": "No audio captured"}

    audio_bytes = b"".join(chunks)
    result = await server_client.identify_voice(audio_bytes)
    if result and result.get("name"):
        return {"name": result["name"], "confidence": result["confidence"]}
    return {"name": None, "confidence": result.get("confidence", 0.0) if result else 0.0}


@mcp_tool(
    name="identify_person_in_view",
    description="Try to identify the person currently visible in the camera by their face.",
    parameters={"type": "object", "properties": {}},
)
async def identify_person_in_view() -> dict:
    from jarvis.core.server_client import server_client
    from jarvis.vision.camera_controller import camera_controller

    if not server_client.server_available:
        return {"status": "error", "message": "Server offline — face identification requires server"}

    frame = await camera_controller.capture_frame()
    if not frame:
        return {"status": "error", "message": "Could not capture camera frame"}

    result = await server_client.identify_face(frame)
    if result and result.get("name"):
        await server_client.record_encounter(result["name"])
        return {"name": result["name"], "confidence": result["confidence"]}
    return {"name": None, "message": "No recognized face in view"}


@mcp_tool(
    name="get_person_info",
    description="Get stored information about a known person including preferences and encounter history.",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The person's name to look up.",
            },
        },
        "required": ["name"],
    },
)
async def get_person_info(name: str) -> dict:
    from jarvis.core.server_client import server_client

    if not server_client.server_available:
        # Fall back to local entity memory
        from jarvis.memory.conversation_memory import conversation_memory
        entity = await conversation_memory.get_entity(name)
        if entity:
            return {"name": name, "source": "local_memory", **entity}
        return {"name": name, "status": "not_found"}

    person = await server_client.get_person(name)
    if person:
        return person
    return {"name": name, "status": "not_found"}
