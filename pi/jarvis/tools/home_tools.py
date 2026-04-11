"""
Home Automation MCP Tools — MQTT, Home Assistant, GPIO relays.
"""

from typing import Any

from jarvis.tools.mcp_server import mcp_tool


@mcp_tool(
    name="control_light",
    description="Turn a light on or off by room/device name.",
    parameters={
        "type": "object",
        "properties": {
            "room": {"type": "string", "description": "Room or device name (e.g., 'relay_0', 'bedroom')"},
            "state": {"type": "boolean", "description": "true = on, false = off"},
        },
        "required": ["room", "state"],
    },
)
async def control_light(room: str, state: bool) -> dict[str, Any]:
    from jarvis.drivers.gpio_controller import gpio_controller
    return await gpio_controller.control_light(room, state)


@mcp_tool(
    name="control_relay",
    description="Control a specific relay by GPIO pin number.",
    parameters={
        "type": "object",
        "properties": {
            "pin": {"type": "integer", "description": "GPIO pin number"},
            "state": {"type": "boolean", "description": "true = on, false = off"},
        },
        "required": ["pin", "state"],
    },
)
async def control_relay(pin: int, state: bool) -> dict[str, Any]:
    from jarvis.drivers.gpio_controller import gpio_controller
    return await gpio_controller.control_relay(pin, state)


@mcp_tool(
    name="get_relay_states",
    description="Get the current state of all configured relays.",
    parameters={"type": "object", "properties": {}},
)
async def get_relay_states() -> dict[str, Any]:
    from jarvis.drivers.gpio_controller import gpio_controller
    states = await gpio_controller.get_relay_states()
    return {"relays": {str(k): "on" if v else "off" for k, v in states.items()}}


@mcp_tool(
    name="publish_mqtt",
    description="Publish a message to an MQTT topic (for Home Assistant or other IoT devices).",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "MQTT topic path"},
            "payload": {"type": "string", "description": "Message payload"},
        },
        "required": ["topic", "payload"],
    },
)
async def publish_mqtt(topic: str, payload: str) -> dict[str, Any]:
    import asyncio
    from jarvis.config import settings

    if not settings.MQTT_BROKER:
        return {"error": "MQTT not configured"}

    try:
        import paho.mqtt.publish as publish
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: publish.single(
                topic,
                payload=payload,
                hostname=settings.MQTT_BROKER,
                port=settings.MQTT_PORT,
                auth={"username": settings.MQTT_USERNAME, "password": settings.MQTT_PASSWORD}
                if settings.MQTT_USERNAME else None,
            ),
        )
        return {"status": "published", "topic": topic}
    except Exception as e:
        return {"error": str(e)}
