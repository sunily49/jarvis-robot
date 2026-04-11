"""
Motor MCP Tools — movement commands for Gemini function calling.

All commands pass through the safety gate in motor_controller.
"""

from typing import Any

from jarvis.tools.mcp_server import mcp_tool


@mcp_tool(
    name="move_forward",
    description="Move the robot forward by a specified distance in centimeters. Safety checks are automatic.",
    parameters={
        "type": "object",
        "properties": {
            "distance_cm": {"type": "integer", "description": "Distance to move in cm", "default": 50},
            "speed": {"type": "integer", "description": "Speed 0-100 (0 = default)", "default": 0},
        },
    },
)
async def move_forward(distance_cm: int = 50, speed: int = 0) -> dict[str, Any]:
    from jarvis.drivers.motor_controller import motor_controller
    return await motor_controller.move_forward(distance_cm, speed)


@mcp_tool(
    name="move_backward",
    description="Move the robot backward by a specified distance in centimeters.",
    parameters={
        "type": "object",
        "properties": {
            "distance_cm": {"type": "integer", "default": 50},
        },
    },
)
async def move_backward(distance_cm: int = 50) -> dict[str, Any]:
    from jarvis.drivers.motor_controller import motor_controller
    return await motor_controller.move_backward(distance_cm)


@mcp_tool(
    name="turn_left",
    description="Turn the robot left by specified degrees.",
    parameters={
        "type": "object",
        "properties": {
            "degrees": {"type": "integer", "default": 90},
        },
    },
)
async def turn_left(degrees: int = 90) -> dict[str, Any]:
    from jarvis.drivers.motor_controller import motor_controller
    return await motor_controller.turn_left(degrees)


@mcp_tool(
    name="turn_right",
    description="Turn the robot right by specified degrees.",
    parameters={
        "type": "object",
        "properties": {
            "degrees": {"type": "integer", "default": 90},
        },
    },
)
async def turn_right(degrees: int = 90) -> dict[str, Any]:
    from jarvis.drivers.motor_controller import motor_controller
    return await motor_controller.turn_right(degrees)


@mcp_tool(
    name="emergency_stop",
    description="Immediately stop all motors. Use in dangerous situations.",
    parameters={"type": "object", "properties": {}},
)
async def emergency_stop() -> dict[str, Any]:
    from jarvis.drivers.motor_controller import motor_controller
    return await motor_controller.emergency_stop()
