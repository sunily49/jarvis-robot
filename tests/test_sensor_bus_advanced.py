"""Advanced SensorBus tests — multiple sensors, readings, threshold edge cases."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "pi"))


@pytest.fixture
def bus():
    from jarvis.drivers.sensor_bus import SensorBus
    return SensorBus()


def test_register_multiple_sensors(bus):
    bus.register("temp", read_fn=lambda: 25.0, interval=1.0, unit="°C")
    bus.register("humidity", read_fn=lambda: 60.0, interval=2.0, unit="%")
    bus.register("distance", read_fn=lambda: 150.0, interval=0.5, unit="cm")
    sensors = bus.list_sensors()
    assert "temp" in sensors
    assert "humidity" in sensors
    assert "distance" in sensors


def test_get_all_readings_empty(bus):
    assert bus.get_all_readings() == {}


def test_get_all_readings_after_registration(bus):
    bus.register("mock_sensor", read_fn=lambda: 10.0, interval=1.0)
    # No readings yet since not started
    readings = bus.get_all_readings()
    assert readings == {}


def test_get_reading_after_manual_inject(bus):
    from jarvis.drivers.sensor_bus import SensorReading
    bus.register("injected", read_fn=lambda: 99.0, interval=1.0, unit="V")
    bus._readings["injected"] = SensorReading(value=99.0, unit="V")
    r = bus.get_reading("injected")
    assert r is not None
    assert r["value"] == 99.0
    assert r["unit"] == "V"
    assert "timestamp" in r


def test_set_threshold_stores_config(bus):
    bus.register("sensor1", read_fn=lambda: 0, interval=1.0)
    bus.set_threshold("sensor1", min_val=10, max_val=50)
    t = bus._thresholds.get("sensor1")
    assert t is not None
    assert t.min_val == 10
    assert t.max_val == 50


def test_set_threshold_default_event_name(bus):
    bus.register("mytest", read_fn=lambda: 0, interval=1.0)
    bus.set_threshold("mytest", min_val=0)
    t = bus._thresholds["mytest"]
    assert t.event == "sensor.mytest.alert"


def test_set_threshold_custom_event_name(bus):
    bus.register("custom", read_fn=lambda: 0, interval=1.0)
    bus.set_threshold("custom", min_val=0, event="custom.alert.event")
    assert bus._thresholds["custom"].event == "custom.alert.event"


@pytest.mark.asyncio
async def test_check_threshold_below_min():
    from jarvis.core.event_bus import EventBus
    from jarvis.drivers.sensor_bus import SensorBus
    import jarvis.core.event_bus as eb_module

    bus = SensorBus()
    alerts = []

    async def on_alert(event, data):
        alerts.append(data)

    eb = EventBus()
    await eb.subscribe("sensor.cold.alert", on_alert)
    original = eb_module.event_bus
    eb_module.event_bus = eb

    bus.register("cold", read_fn=lambda: 0, interval=1.0)
    bus.set_threshold("cold", min_val=10, max_val=40)

    # Below min
    await bus._check_threshold("cold", 5.0)
    assert len(alerts) == 1
    assert alerts[0]["sensor"] == "cold"
    assert alerts[0]["value"] == 5.0

    eb_module.event_bus = original


@pytest.mark.asyncio
async def test_check_threshold_above_max():
    from jarvis.core.event_bus import EventBus
    from jarvis.drivers.sensor_bus import SensorBus
    import jarvis.core.event_bus as eb_module

    bus = SensorBus()
    alerts = []

    async def on_alert(event, data):
        alerts.append(data)

    eb = EventBus()
    await eb.subscribe("sensor.hot.alert", on_alert)
    original = eb_module.event_bus
    eb_module.event_bus = eb

    bus.register("hot", read_fn=lambda: 0, interval=1.0)
    bus.set_threshold("hot", min_val=10, max_val=40)

    await bus._check_threshold("hot", 95.0)
    assert len(alerts) == 1
    assert alerts[0]["value"] == 95.0

    eb_module.event_bus = original


@pytest.mark.asyncio
async def test_check_threshold_within_range_no_alert():
    from jarvis.core.event_bus import EventBus
    from jarvis.drivers.sensor_bus import SensorBus
    import jarvis.core.event_bus as eb_module

    bus = SensorBus()
    alerts = []

    async def on_alert(event, data):
        alerts.append(data)

    eb = EventBus()
    await eb.subscribe("sensor.ok.alert", on_alert)
    original = eb_module.event_bus
    eb_module.event_bus = eb

    bus.register("ok", read_fn=lambda: 0, interval=1.0)
    bus.set_threshold("ok", min_val=10, max_val=40)

    await bus._check_threshold("ok", 25.0)
    assert len(alerts) == 0

    eb_module.event_bus = original


@pytest.mark.asyncio
async def test_check_threshold_non_numeric_value():
    from jarvis.drivers.sensor_bus import SensorBus
    bus = SensorBus()
    bus.register("str_sensor", read_fn=lambda: "hello", interval=1.0)
    bus.set_threshold("str_sensor", min_val=0, max_val=100)
    # Should not raise
    await bus._check_threshold("str_sensor", "not_a_number")


def test_sensor_reading_dataclass():
    from jarvis.drivers.sensor_bus import SensorReading
    r = SensorReading(value=42.5, unit="kPa", raw=b"\x00")
    assert r.value == 42.5
    assert r.unit == "kPa"
    assert r.raw == b"\x00"
    assert r.timestamp > 0


def test_sensor_config_dataclass():
    from jarvis.drivers.sensor_bus import SensorConfig
    config = SensorConfig(name="test", read_fn=lambda: 1, interval=5.0, unit="m")
    assert config.name == "test"
    assert config.interval == 5.0
    assert config.unit == "m"
    assert config.enabled is True
