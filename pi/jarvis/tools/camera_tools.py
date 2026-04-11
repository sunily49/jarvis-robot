"""
Camera MCP Tools — PTZ control, scene analysis, and face-aware scanning for Gemini.

On-demand scan flow:
  Gemini calls scan_and_find_people or scan_environment
    → camera physically pans 8 × 45° positions
    → JPEG captured at each position
    → face recognition run in parallel on all frames (server)
    → profiles fetched for known people
    → Gemini gets back: who was seen, where, confidence, and profile context
"""

import asyncio
import logging
from typing import Any

from jarvis.tools.mcp_server import mcp_tool

logger = logging.getLogger(__name__)


@mcp_tool(
    name="pan_to_angle",
    description="Pan the camera to a specific angle. Range: -36000 to 36000 (v4l2 units). 0 = center.",
    parameters={
        "type": "object",
        "properties": {
            "angle": {"type": "integer", "description": "Pan angle in v4l2 units"},
        },
        "required": ["angle"],
    },
)
async def pan_to_angle(angle: int) -> dict[str, Any]:
    from jarvis.vision.camera_controller import camera_controller
    await camera_controller.pan_to(angle)
    return {"status": "ok", "angle": angle}


@mcp_tool(
    name="look_at_direction",
    description="Pan camera to a named direction: center, left, right, hard_left, hard_right.",
    parameters={
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["center", "left", "right", "hard_left", "hard_right"],
            },
        },
        "required": ["direction"],
    },
)
async def look_at_direction(direction: str) -> dict[str, Any]:
    from jarvis.vision.camera_controller import camera_controller
    await camera_controller.look_at_direction(direction)
    return {"status": "ok", "direction": direction}


@mcp_tool(
    name="scan_environment",
    description=(
        "Perform a 360-degree camera scan at 8 positions (45° apart). "
        "Returns scene descriptions AND any identified people if server is available. "
        "Use scan_and_find_people if you specifically want to identify who is in the room."
    ),
    parameters={"type": "object", "properties": {}},
)
async def scan_environment() -> dict[str, Any]:
    from jarvis.vision.camera_controller import camera_controller, PAN_MIN, PAN_MAX, SCAN_STEPS
    from jarvis.ai.gemini_flash import gemini_flash
    from jarvis.core.server_client import server_client

    frames = await camera_controller.scan_environment()
    if not frames:
        return {"error": "No frames captured"}

    step_size = (PAN_MAX - PAN_MIN) // SCAN_STEPS
    angles = [PAN_MIN + (step_size * i) for i in range(len(frames))]

    # Scene descriptions (parallel, first 4 frames for speed)
    desc_results = await asyncio.gather(
        *[gemini_flash.describe_scene(f) for f in frames[:4]],
        return_exceptions=True,
    )
    descriptions = [
        f"Position {i + 1}: {r}"
        for i, r in enumerate(desc_results)
        if isinstance(r, str) and r
    ]

    # Face identification — parallel across all 8 frames
    identified_people: list[dict[str, Any]] = []
    if server_client.server_available:
        face_results = await asyncio.gather(
            *[server_client.identify_face(f) for f in frames],
            return_exceptions=True,
        )
        # Deduplicate: keep highest confidence result per name
        best: dict[str, dict[str, Any]] = {}
        for i, result in enumerate(face_results):
            if isinstance(result, Exception) or not result:
                continue
            name = result.get("name")
            confidence = result.get("confidence", 0.0)
            if name and confidence > 0:
                if name not in best or confidence > best[name]["confidence"]:
                    best[name] = {
                        "name": name,
                        "confidence": round(confidence, 3),
                        "angle": angles[i],
                    }

        identified_people = list(best.values())

        # Record encounters without blocking the return
        for person in identified_people:
            asyncio.ensure_future(server_client.record_encounter(person["name"]))

        logger.info(
            "Scan complete: %d positions, %d people identified",
            len(frames), len(identified_people),
        )

    return {
        "scan_positions": len(frames),
        "descriptions": descriptions,
        "identified_people": identified_people,
        "server_available": server_client.server_available,
    }


@mcp_tool(
    name="capture_and_describe",
    description=(
        "Capture a single photo from the camera, describe the scene, "
        "and identify any person visible if the server is available."
    ),
    parameters={"type": "object", "properties": {}},
)
async def capture_and_describe() -> dict[str, Any]:
    from jarvis.vision.camera_controller import camera_controller
    from jarvis.ai.gemini_flash import gemini_flash
    from jarvis.core.server_client import server_client

    frame = await camera_controller.capture_frame()
    if not frame:
        return {"error": "Camera unavailable"}

    # Run description and face ID in parallel when server is available
    if server_client.server_available:
        desc_result, face_result = await asyncio.gather(
            gemini_flash.describe_scene(frame),
            server_client.identify_face(frame),
            return_exceptions=True,
        )
    else:
        desc_result = await gemini_flash.describe_scene(frame)
        face_result = None

    result: dict[str, Any] = {
        "description": desc_result if isinstance(desc_result, str) else None,
        "identified_person": None,
    }

    if face_result and not isinstance(face_result, Exception):
        name = face_result.get("name")
        if name:
            result["identified_person"] = {
                "name": name,
                "confidence": round(face_result.get("confidence", 0.0), 3),
            }
            asyncio.ensure_future(server_client.record_encounter(name))

    return result


@mcp_tool(
    name="scan_and_find_people",
    description=(
        "Perform a full 360-degree scan specifically to find and identify people in the room. "
        "Physically pans camera through 8 positions (45° each), runs face recognition on every "
        "frame in parallel, deduplicates results, and fetches profiles for all known people. "
        "Returns who was seen, their confidence, angle, and stored profile (preferences/notes). "
        "Use this when asked: 'who is in the room?', 'scan for people', 'look around'. "
        "Requires server — use scan_environment if server is offline."
    ),
    parameters={"type": "object", "properties": {}},
)
async def scan_and_find_people() -> dict[str, Any]:
    from jarvis.vision.camera_controller import camera_controller, PAN_MIN, PAN_MAX, SCAN_STEPS
    from jarvis.core.server_client import server_client

    if not server_client.server_available:
        return {
            "error": (
                "Face recognition requires the server, which is currently offline. "
                "Try scan_environment for a visual description without face identification."
            )
        }

    frames = await camera_controller.scan_environment()
    if not frames:
        return {"error": "No frames captured during scan"}

    step_size = (PAN_MAX - PAN_MIN) // SCAN_STEPS
    angles = [PAN_MIN + (step_size * i) for i in range(len(frames))]

    # Parallel face ID across all frames
    face_results = await asyncio.gather(
        *[server_client.identify_face(f) for f in frames],
        return_exceptions=True,
    )

    # Deduplicate by name, keep highest confidence; count unrecognized faces
    best: dict[str, dict[str, Any]] = {}
    unknown_count = 0

    for i, result in enumerate(face_results):
        if isinstance(result, Exception) or not result:
            continue
        name = result.get("name")
        confidence = result.get("confidence", 0.0)
        if name and confidence > 0:
            if name not in best or confidence > best[name]["confidence"]:
                best[name] = {
                    "name": name,
                    "confidence": round(confidence, 3),
                    "angle": angles[i],
                    "profile": None,  # filled below
                }
        elif confidence > 0:
            # Face detected but not in registry
            unknown_count += 1

    # Parallel profile fetch for all identified people
    known_names = list(best.keys())
    if known_names:
        profiles = await asyncio.gather(
            *[server_client.get_person(n) for n in known_names],
            return_exceptions=True,
        )
        for name, profile in zip(known_names, profiles):
            if not isinstance(profile, Exception) and profile:
                best[name]["profile"] = profile

        # Record encounters (fire-and-forget — don't block return)
        for name in known_names:
            asyncio.ensure_future(server_client.record_encounter(name))

    logger.info(
        "People scan: %d known, %d unknown across %d positions",
        len(best), unknown_count, len(frames),
    )

    return {
        "known_people": list(best.values()),
        "unknown_count": unknown_count,
        "scan_positions": len(frames),
    }


@mcp_tool(
    name="detect_objects_in_view",
    description="Detect objects in the current camera view using YOLOv8 (requires server).",
    parameters={"type": "object", "properties": {}},
)
async def detect_objects_in_view() -> dict[str, Any]:
    from jarvis.vision.camera_controller import camera_controller
    from jarvis.core.server_client import server_client

    if not server_client.server_available:
        return {"error": "Object detection requires server — server is offline"}

    frame = await camera_controller.capture_frame()
    if not frame:
        return {"error": "Camera unavailable"}

    detections = await server_client.detect_objects(frame)
    return {"detections": detections or []}
