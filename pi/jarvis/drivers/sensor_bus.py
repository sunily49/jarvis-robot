"""
SensorBus — unified registry for all sensors.

Design:
- Plugin pattern: each sensor type registers itself with a name, read function, and config
- Unified dict holds latest reading + timestamp for every sensor
- Two modes: Pull (on-demand read) and Push (threshold → auto event via EventBus)
- Adding a new sensor = register it + optionally set a threshold

Usage:
    # Register a new sensor type
    sensor_bus.register("dht22_temp", read_fn=read_dht22_temp, interval=5.0)
    sensor_bus.register("ultrasonic_front", read_fn=read_hcsr04, interval=0.5)

    # Set threshold for auto-alert
    sensor_bus.set_threshold("dht22_temp", min_val=5, max_val=45, event="sensor.temp_alert")

    # Read on demand
    reading = sensor_bus.get_reading("dht22_temp")
    # → {"value": 23.5, "timestamp": 1712345678.9, "unit": "°C"}
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from jarvis.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SensorReading:
    value: Any
    timestamp: float = field(default_factory=time.time)
    unit: str = ""
    raw: Any = None


@dataclass
class SensorConfig:
    name: str
    read_fn: Callable[[], Any]  # Blocking callable that reads the sensor
    interval: float = 5.0       # Polling interval in seconds
    unit: str = ""
    enabled: bool = True


@dataclass
class ThresholdConfig:
    min_val: float | None = None
    max_val: float | None = None
    event: str = ""  # EventBus event to publish on breach


class SensorBus:
    """Unified sensor registry with polling and threshold alerts."""

    def __init__(self) -> None:
        self._sensors: dict[str, SensorConfig] = {}
        self._readings: dict[str, SensorReading] = {}
        self._thresholds: dict[str, ThresholdConfig] = {}
        self._tasks: list[asyncio.Task] = []
        self._running = False

    def register(
        self,
        name: str,
        read_fn: Callable[[], Any],
        interval: float = 5.0,
        unit: str = "",
        enabled: bool = True,
    ) -> None:
        """Register a new sensor. Call before start()."""
        self._sensors[name] = SensorConfig(
            name=name, read_fn=read_fn, interval=interval, unit=unit, enabled=enabled,
        )
        logger.info("Sensor registered: %s (interval=%.1fs, unit=%s)", name, interval, unit)

    def set_threshold(
        self,
        name: str,
        min_val: float | None = None,
        max_val: float | None = None,
        event: str = "",
    ) -> None:
        """Set auto-alert threshold for a sensor."""
        self._thresholds[name] = ThresholdConfig(
            min_val=min_val,
            max_val=max_val,
            event=event or f"sensor.{name}.alert",
        )

    async def start(self) -> None:
        """Start polling all registered sensors."""
        if not settings.HW_SENSORS:
            logger.info("Sensors disabled in config")
            return
        self._running = True
        for name, config in self._sensors.items():
            if config.enabled:
                task = asyncio.create_task(self._poll_loop(name, config))
                self._tasks.append(task)
        logger.info("SensorBus started (%d sensors)", len(self._tasks))

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        logger.info("SensorBus stopped")

    async def _poll_loop(self, name: str, config: SensorConfig) -> None:
        """Poll a single sensor at its configured interval."""
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                value = await loop.run_in_executor(None, config.read_fn)
                reading = SensorReading(value=value, unit=config.unit)
                self._readings[name] = reading

                # Check thresholds
                await self._check_threshold(name, value)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Sensor '%s' read error", name)

            await asyncio.sleep(config.interval)

    async def _check_threshold(self, name: str, value: Any) -> None:
        """Check if a reading breaches a threshold and publish alert."""
        threshold = self._thresholds.get(name)
        if not threshold:
            return
        try:
            val = float(value)
        except (TypeError, ValueError):
            return

        breached = False
        if threshold.min_val is not None and val < threshold.min_val:
            breached = True
        if threshold.max_val is not None and val > threshold.max_val:
            breached = True

        if breached:
            from jarvis.core.event_bus import event_bus
            await event_bus.publish(threshold.event, {
                "sensor": name,
                "value": val,
                "threshold": {
                    "min": threshold.min_val,
                    "max": threshold.max_val,
                },
            })
            logger.warning(
                "Sensor '%s' threshold breached: value=%s (min=%s, max=%s)",
                name, val, threshold.min_val, threshold.max_val,
            )

    def get_reading(self, name: str) -> dict[str, Any] | None:
        """Get the latest reading for a sensor (pull mode)."""
        reading = self._readings.get(name)
        if not reading:
            return None
        return {
            "value": reading.value,
            "timestamp": reading.timestamp,
            "unit": reading.unit,
        }

    def get_all_readings(self) -> dict[str, dict[str, Any]]:
        """Get all sensor readings."""
        return {
            name: {
                "value": r.value,
                "timestamp": r.timestamp,
                "unit": r.unit,
            }
            for name, r in self._readings.items()
        }

    def list_sensors(self) -> list[str]:
        return list(self._sensors.keys())


# Singleton
sensor_bus = SensorBus()


# ── Built-in sensor read functions (register these in main.py if enabled) ────

def read_hcsr04_front() -> float:
    """Read HC-SR04 ultrasonic distance sensor (front). Returns cm."""
    import RPi.GPIO as GPIO
    import time

    TRIG = 23  # Configurable
    ECHO = 24

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(TRIG, GPIO.OUT)
    GPIO.setup(ECHO, GPIO.IN)

    GPIO.output(TRIG, True)
    time.sleep(0.00001)
    GPIO.output(TRIG, False)

    start = time.time()
    timeout = start + 0.04  # 40ms max

    while GPIO.input(ECHO) == 0 and time.time() < timeout:
        start = time.time()

    stop = time.time()
    while GPIO.input(ECHO) == 1 and time.time() < timeout:
        stop = time.time()

    distance = (stop - start) * 34300 / 2  # Speed of sound / 2
    return round(distance, 1)


def read_dht22() -> dict:
    """Read DHT22 temperature + humidity sensor. Returns {temp, humidity}."""
    try:
        import adafruit_dht
        import board
        dht = adafruit_dht.DHT22(board.D4)
        return {"temperature": dht.temperature, "humidity": dht.humidity}
    except Exception:
        return {"temperature": None, "humidity": None}
