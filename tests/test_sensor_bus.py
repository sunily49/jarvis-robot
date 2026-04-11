"""Tests for SensorBus — registration, reading, thresholds."""

import asyncio
import pytest

from jarvis.drivers.sensor_bus import SensorBus


@pytest.fixture
def bus():
    return SensorBus()


def test_register_sensor(bus):
    bus.register("test_sensor", read_fn=lambda: 42.0, interval=1.0, unit="°C")
    assert "test_sensor" in bus.list_sensors()


def test_get_reading_before_poll(bus):
    bus.register("test", read_fn=lambda: 0)
    assert bus.get_reading("test") is None


def test_get_reading_nonexistent(bus):
    assert bus.get_reading("missing") is None


@pytest.mark.asyncio
async def test_threshold_alert():
    from jarvis.core.event_bus import EventBus

    bus = SensorBus()
    alerts = []

    async def on_alert(event, data):
        alerts.append(data)

    # Use a fresh event bus
    eb = EventBus()
    await eb.subscribe("sensor.test.alert", on_alert)

    # Monkey-patch
    import jarvis.drivers.sensor_bus as sb_module
    import jarvis.core.event_bus as eb_module
    original = eb_module.event_bus
    eb_module.event_bus = eb

    counter = {"val": 25.0}

    def read_fn():
        return counter["val"]

    bus.register("test", read_fn=read_fn, interval=0.1, unit="°C")
    bus.set_threshold("test", min_val=10, max_val=40)

    # Normal value — no alert
    bus._readings["test"] = type("R", (), {"value": 25.0, "timestamp": 0, "unit": "°C"})()
    await bus._check_threshold("test", 25.0)
    assert len(alerts) == 0

    # Anomalous value — should alert
    await bus._check_threshold("test", 50.0)
    assert len(alerts) == 1
    assert alerts[0]["sensor"] == "test"

    eb_module.event_bus = original
