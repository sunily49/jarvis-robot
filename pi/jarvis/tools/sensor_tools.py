"""
Sensor MCP Tools — read sensors and check anomalies for Gemini.
"""

from typing import Any

from jarvis.tools.mcp_server import mcp_tool


@mcp_tool(
    name="read_sensor",
    description="Read a specific sensor by name. Returns value, unit, and timestamp.",
    parameters={
        "type": "object",
        "properties": {
            "sensor_name": {"type": "string", "description": "Name of the sensor (e.g., 'dht22_temp', 'ultrasonic_front')"},
        },
        "required": ["sensor_name"],
    },
)
async def read_sensor(sensor_name: str) -> dict[str, Any]:
    from jarvis.drivers.sensor_bus import sensor_bus
    reading = sensor_bus.get_reading(sensor_name)
    if reading is None:
        return {"error": f"Sensor '{sensor_name}' not found or no reading available"}
    return reading


@mcp_tool(
    name="list_sensors",
    description="List all registered sensors and their latest readings.",
    parameters={"type": "object", "properties": {}},
)
async def list_sensors() -> dict[str, Any]:
    from jarvis.drivers.sensor_bus import sensor_bus
    return {
        "sensors": sensor_bus.list_sensors(),
        "readings": sensor_bus.get_all_readings(),
    }


@mcp_tool(
    name="get_environment_status",
    description="Get a summary of all environmental sensor readings (temperature, humidity, light, etc.).",
    parameters={"type": "object", "properties": {}},
)
async def get_environment_status() -> dict[str, Any]:
    from jarvis.drivers.sensor_bus import sensor_bus
    readings = sensor_bus.get_all_readings()
    return {"environment": readings}
