"""
Camera MCP Tools — PTZ control and scene analysis for Gemini.
"""

from typing import Any

from jarvis.tools.mcp_server import mcp_tool


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
            "direction": {"type": "string", "enum": ["center", "left", "right", "hard_left", "hard_right"]},
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
    description="Perform a 360-degree scan, capturing frames at 8 positions. Returns scene description.",
    parameters={"type": "object", "properties": {}},
)
async def scan_environment() -> dict[str, Any]:
    from jarvis.vision.camera_controller import camera_controller
    from jarvis.ai.gemini_flash import gemini_flash

    frames = await camera_controller.scan_environment()
    if not frames:
        return {"error": "No frames captured"}

    # Send first and last frame to Gemini for scene description
    descriptions = []
    for i, frame in enumerate(frames[:4]):  # Limit to 4 for speed
        desc = await gemini_flash.describe_scene(frame)
        if desc:
            descriptions.append(f"Position {i+1}: {desc}")

    return {"scan_positions": len(frames), "descriptions": descriptions}


@mcp_tool(
    name="capture_and_describe",
    description="Capture a photo and describe what the camera currently sees.",
    parameters={"type": "object", "properties": {}},
)
async def capture_and_describe() -> dict[str, Any]:
    from jarvis.vision.camera_controller import camera_controller
    from jarvis.ai.gemini_flash import gemini_flash

    frame = await camera_controller.capture_frame()
    if not frame:
        return {"error": "Camera unavailable"}

    description = await gemini_flash.describe_scene(frame)
    return {"description": description}


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
