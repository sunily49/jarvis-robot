"""
JARVIS Robot — Main Entry Point

Asyncio-based application that:
1. Loads only enabled modules from .env feature flags
2. Starts all registered triggers concurrently
3. Manages Gemini Live sessions
4. Runs MCP tool server
5. Auto-restarts on crash (systemd handles outer restart)
"""

import asyncio
import logging
import signal
import sys

from jarvis.config import settings

# ── Logging setup ─────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("jarvis")


# ── Dynamic module loader ─────────────────────────────────────────────

def load_enabled_modules() -> None:
    """Import modules whose feature flag is True. Each module self-registers on import."""
    logger.info("Loading enabled modules...")

    # Triggers
    if settings.TRIGGER_WAKEWORD:
        import jarvis.triggers.wakeword_trigger  # noqa: F401
    if settings.TRIGGER_BUTTON:
        import jarvis.triggers.button_trigger  # noqa: F401
    if settings.TRIGGER_FACE:
        import jarvis.triggers.face_trigger  # noqa: F401
    if settings.TRIGGER_CLAP:
        import jarvis.triggers.clap_trigger  # noqa: F401
    if settings.TRIGGER_PIR:
        import jarvis.triggers.pir_trigger  # noqa: F401
    if settings.TRIGGER_TELEGRAM:
        import jarvis.triggers.telegram_trigger  # noqa: F401

    # MCP Tools
    if settings.TOOL_CAMERA_PTZ:
        import jarvis.tools.camera_tools  # noqa: F401
    if settings.TOOL_MOTOR:
        import jarvis.tools.motor_tools  # noqa: F401
    if settings.TOOL_GPIO:
        import jarvis.tools.home_tools  # noqa: F401
    if settings.TOOL_WEB_SEARCH:
        import jarvis.tools.web_tools  # noqa: F401
    if settings.TOOL_MUSIC:
        import jarvis.tools.music_tools  # noqa: F401
    if settings.TOOL_MEMORY:
        import jarvis.tools.memory_tools  # noqa: F401

    # Person recognition tools (face + voice) — needs server + camera
    if settings.VISION_FACE_RECOGNITION:
        import jarvis.tools.person_tools  # noqa: F401

    # Display tools
    if settings.DISPLAY_ENABLED:
        import jarvis.tools.display_tools  # noqa: F401

    # Sensor tools always loaded if sensors enabled
    if settings.HW_SENSORS:
        import jarvis.tools.sensor_tools  # noqa: F401

    from jarvis.core.trigger_manager import TriggerManager
    logger.info("Loaded triggers: %s", TriggerManager.get_registered())

    from jarvis.tools.mcp_server import get_tool_schemas
    logger.info("Loaded tools: %d", len(get_tool_schemas()))


# ── Sensor registration ──────────────────────────────────────────────

def register_sensors() -> None:
    """Register hardware sensors with the SensorBus."""
    if not settings.HW_SENSORS:
        return

    from jarvis.drivers.sensor_bus import sensor_bus, read_hcsr04_front, read_dht22

    sensor_bus.register("ultrasonic_front", read_fn=read_hcsr04_front, interval=0.5, unit="cm")
    sensor_bus.register("dht22", read_fn=read_dht22, interval=5.0, unit="°C/%RH")

    # Set alert thresholds
    sensor_bus.set_threshold("ultrasonic_front", min_val=5, max_val=400)
    sensor_bus.set_threshold("dht22", min_val=5, max_val=50, event="sensor.temp_alert")

    logger.info("Sensors registered: %s", sensor_bus.list_sensors())


# ── Main application ──────────────────────────────────────────────────

async def startup() -> None:
    """Initialize all subsystems."""
    logger.info("=" * 60)
    logger.info("JARVIS Robot starting up...")
    logger.info("=" * 60)

    # Load feature-flagged modules
    load_enabled_modules()
    register_sensors()

    # Initialize core services
    from jarvis.audio.capture import audio_capture
    from jarvis.audio.playback import audio_playback
    from jarvis.audio.tts import tts
    from jarvis.core.server_client import server_client
    from jarvis.core.session_manager import SessionManager
    from jarvis.memory.conversation_memory import conversation_memory

    # Start audio pipeline
    await audio_capture.start()
    await audio_playback.start()

    # Start server client (health monitoring)
    await server_client.start()

    # Start network monitor (selects AI backend: Gemini / local / offline)
    from jarvis.core.network_monitor import network_monitor
    await network_monitor.start()

    # Initialize memory
    await conversation_memory.initialize()

    # Start hardware drivers if enabled
    if settings.TOOL_GPIO:
        from jarvis.drivers.gpio_controller import gpio_controller
        await gpio_controller.start()

    if settings.HW_MOTORS:
        from jarvis.drivers.motor_controller import motor_controller
        await motor_controller.start()

    if settings.HW_SERVOS:
        from jarvis.drivers.servo_controller import servo_controller
        await servo_controller.start()

    if settings.TOOL_CAMERA_PTZ:
        from jarvis.vision.camera_controller import camera_controller
        await camera_controller.start()

    # Start sensor bus
    if settings.HW_SENSORS:
        from jarvis.drivers.sensor_bus import sensor_bus
        await sensor_bus.start()

    # Initialize session manager
    session_mgr = SessionManager()
    await session_mgr.initialize()

    # Register tools with Gemini Live
    from jarvis.tools.mcp_server import get_tool_schemas_dict
    # Tools will be passed to GeminiLiveClient on session start

    # Start display if enabled
    if settings.DISPLAY_ENABLED:
        from jarvis.display.ui_manager import UIManager
        global _ui_manager
        _ui_manager = UIManager()
        await _ui_manager.start()

    # Announce ready
    await tts.announce("JARVIS online. All systems operational.")

    logger.info("Startup complete. Listening for triggers...")
    return session_mgr


async def run() -> None:
    """Main run loop — starts all concurrent tasks."""
    session_mgr = await startup()

    from jarvis.core.trigger_manager import TriggerManager
    from jarvis.tools.mcp_server import start_mcp_server

    # Gather all long-running tasks
    tasks = [
        asyncio.create_task(TriggerManager.start_all(), name="triggers"),
        asyncio.create_task(start_mcp_server(), name="mcp_server"),
    ]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Shutdown signal received")
    finally:
        await shutdown(session_mgr)


_ui_manager = None  # Module-level reference for display


async def shutdown(session_mgr=None) -> None:
    """Graceful shutdown of all subsystems."""
    logger.info("Shutting down JARVIS...")

    global _ui_manager
    if _ui_manager:
        await _ui_manager.stop()
        _ui_manager = None

    from jarvis.core.trigger_manager import TriggerManager
    from jarvis.audio.capture import audio_capture
    from jarvis.audio.playback import audio_playback
    from jarvis.core.server_client import server_client
    from jarvis.memory.conversation_memory import conversation_memory

    await TriggerManager.stop_all()

    if session_mgr:
        await session_mgr.shutdown()

    await audio_capture.stop()
    await audio_playback.stop()
    await server_client.stop()

    from jarvis.core.network_monitor import network_monitor
    await network_monitor.stop()
    await conversation_memory.close()

    if settings.TOOL_CAMERA_PTZ:
        from jarvis.vision.camera_controller import camera_controller
        await camera_controller.stop()

    if settings.HW_MOTORS:
        from jarvis.drivers.motor_controller import motor_controller
        await motor_controller.stop()

    if settings.HW_SERVOS:
        from jarvis.drivers.servo_controller import servo_controller
        await servo_controller.stop()

    if settings.HW_SENSORS:
        from jarvis.drivers.sensor_bus import sensor_bus
        await sensor_bus.stop()

    if settings.TOOL_GPIO:
        from jarvis.drivers.gpio_controller import gpio_controller
        await gpio_controller.stop()

    logger.info("JARVIS shut down cleanly.")


def main() -> None:
    """Entry point."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Handle SIGTERM/SIGINT for graceful shutdown
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(shutdown()))
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler

    try:
        loop.run_until_complete(run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
