"""
MCP Display Tools — allows Gemini to control the robot's screen.
"""

import logging

from jarvis.tools.mcp_server import mcp_tool

logger = logging.getLogger(__name__)


def _get_ui_manager():
    """Lazy import to avoid circular dependency."""
    from jarvis.main import _ui_manager
    return _ui_manager


@mcp_tool(
    name="set_display_screen",
    description="Switch the robot's display to a specific screen mode.",
    parameters={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["face", "status", "conversation", "camera", "split"],
                "description": "Screen mode: face (animated eyes), status (system stats), conversation (chat log), camera (live view), split (face + status)",
            },
        },
        "required": ["mode"],
    },
)
async def set_display_screen(mode: str) -> dict:
    ui = _get_ui_manager()
    if not ui:
        return {"status": "error", "message": "Display not enabled"}
    from jarvis.display.ui_manager import ScreenMode
    mode_map = {m.name.lower(): m for m in ScreenMode}
    screen_mode = mode_map.get(mode.lower())
    if not screen_mode:
        return {"status": "error", "message": f"Unknown mode: {mode}"}
    ui.set_screen(screen_mode)
    return {"status": "ok", "mode": mode}


@mcp_tool(
    name="set_display_emotion",
    description="Set the robot's facial expression/emotion on the display.",
    parameters={
        "type": "object",
        "properties": {
            "emotion": {
                "type": "string",
                "enum": ["neutral", "happy", "sad", "angry", "surprised", "thinking", "listening", "speaking", "sleeping"],
                "description": "The facial expression to show.",
            },
        },
        "required": ["emotion"],
    },
)
async def set_display_emotion(emotion: str) -> dict:
    ui = _get_ui_manager()
    if not ui:
        return {"status": "error", "message": "Display not enabled"}
    from jarvis.display.face_renderer import Emotion
    emotion_map = {e.name.lower(): e for e in Emotion}
    emo = emotion_map.get(emotion.lower())
    if not emo:
        return {"status": "error", "message": f"Unknown emotion: {emotion}"}
    ui.set_emotion(emo)
    return {"status": "ok", "emotion": emotion}


@mcp_tool(
    name="set_display_status",
    description="Show a status message on the robot's display.",
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Status text to display (short, one line).",
            },
        },
        "required": ["text"],
    },
)
async def set_display_status(text: str) -> dict:
    ui = _get_ui_manager()
    if not ui:
        return {"status": "error", "message": "Display not enabled"}
    ui.set_status(text)
    return {"status": "ok", "text": text}
