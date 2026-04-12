"""Advanced TriggerManager tests — priorities, multiple triggers, edge cases."""

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "pi"))

from jarvis.core.trigger_manager import (
    BaseTrigger,
    TriggerEvent,
    TriggerManager,
    TriggerPriority,
)


@pytest.fixture(autouse=True)
def reset_manager():
    TriggerManager._registry.clear()
    TriggerManager._last_trigger_time = 0.0
    TriggerManager._running = False
    TriggerManager._cooldown = 0.05
    yield
    TriggerManager._registry.clear()
    TriggerManager._last_trigger_time = 0.0
    TriggerManager._running = False


class MockTrigger(BaseTrigger):
    def __init__(self, name, priority=TriggerPriority.NORMAL):
        self._name = name
        self._priority = priority
        self.started = False

    @property
    def name(self):
        return self._name

    @property
    def priority(self):
        return self._priority

    async def start(self):
        self.started = True
        while self.started:
            await asyncio.sleep(0.05)

    async def stop(self):
        self.started = False


def test_multiple_triggers_register():
    t1 = MockTrigger("wakeword")
    t2 = MockTrigger("button", TriggerPriority.CRITICAL)
    TriggerManager.register(t1)
    TriggerManager.register(t2)
    registered = TriggerManager.get_registered()
    assert "wakeword" in registered
    assert "button" in registered


def test_priority_enum_ordering():
    assert TriggerPriority.LOW < TriggerPriority.NORMAL
    assert TriggerPriority.NORMAL < TriggerPriority.HIGH
    assert TriggerPriority.HIGH < TriggerPriority.CRITICAL
    assert TriggerPriority.CRITICAL == 100


def test_trigger_event_defaults():
    event = TriggerEvent(source="test")
    assert event.source == "test"
    assert event.priority == TriggerPriority.NORMAL
    assert event.confidence == 1.0
    assert event.data == {}
    assert event.timestamp > 0


def test_set_cooldown():
    TriggerManager.set_cooldown(2.5)
    assert TriggerManager._cooldown == 2.5


@pytest.mark.asyncio
async def test_trigger_fires_event():
    import jarvis.core.trigger_manager as tm
    from jarvis.core.event_bus import EventBus
    bus = EventBus()
    received = []

    async def handler(event, data):
        received.append(data)

    await bus.subscribe("trigger.wakeword", handler)
    original = tm.event_bus
    tm.event_bus = bus

    TriggerManager.set_cooldown(0.0)
    event = TriggerEvent(source="wakeword", priority=TriggerPriority.NORMAL, confidence=0.95)
    await TriggerManager.handle_trigger(event)

    assert len(received) == 1
    assert received[0]["source"] == "wakeword"
    assert received[0]["confidence"] == 0.95

    tm.event_bus = original


@pytest.mark.asyncio
async def test_cooldown_suppresses_rapid_triggers():
    import jarvis.core.trigger_manager as tm
    from jarvis.core.event_bus import EventBus
    bus = EventBus()
    received = []

    async def handler(event, data):
        received.append(data)

    await bus.subscribe("trigger.*", handler)
    original = tm.event_bus
    tm.event_bus = bus

    TriggerManager.set_cooldown(10.0)  # very long cooldown
    TriggerManager._last_trigger_time = 0.0  # reset

    for _ in range(5):
        event = TriggerEvent(source="wakeword")
        await TriggerManager.handle_trigger(event)

    # Only the first should fire
    assert len(received) == 1

    tm.event_bus = original


@pytest.mark.asyncio
async def test_critical_priority_trigger():
    import jarvis.core.trigger_manager as tm
    from jarvis.core.event_bus import EventBus
    bus = EventBus()
    received = []

    async def handler(event, data):
        received.append(data)

    await bus.subscribe("trigger.button", handler)
    original = tm.event_bus
    tm.event_bus = bus

    TriggerManager.set_cooldown(0.0)
    event = TriggerEvent(source="button", priority=TriggerPriority.CRITICAL, confidence=1.0)
    await TriggerManager.handle_trigger(event)

    assert len(received) == 1
    assert received[0]["priority"] == TriggerPriority.CRITICAL

    tm.event_bus = original


@pytest.mark.asyncio
async def test_base_trigger_fire_calls_handle():
    import jarvis.core.trigger_manager as tm
    from jarvis.core.event_bus import EventBus

    bus = EventBus()
    received = []

    async def handler(event, data):
        received.append(data)

    await bus.subscribe("trigger.mock", handler)
    original = tm.event_bus
    tm.event_bus = bus

    TriggerManager.set_cooldown(0.0)
    t = MockTrigger("mock")
    await t.fire(confidence=0.8, data={"test": True})

    assert len(received) == 1
    assert received[0]["confidence"] == 0.8

    tm.event_bus = original


@pytest.mark.asyncio
async def test_trigger_event_includes_timestamp():
    import jarvis.core.trigger_manager as tm
    from jarvis.core.event_bus import EventBus

    bus = EventBus()
    received = []

    async def handler(event, data):
        received.append(data)

    await bus.subscribe("trigger.ts", handler)
    original = tm.event_bus
    tm.event_bus = bus

    TriggerManager.set_cooldown(0.0)
    before = time.time()
    event = TriggerEvent(source="ts")
    await TriggerManager.handle_trigger(event)
    after = time.time()

    assert before <= received[0]["timestamp"] <= after

    tm.event_bus = original
