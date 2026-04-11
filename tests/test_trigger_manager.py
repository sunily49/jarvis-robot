"""Tests for TriggerManager — registration, cooldown, priority."""

import asyncio
import time
import pytest

from jarvis.core.trigger_manager import (
    BaseTrigger,
    TriggerEvent,
    TriggerManager,
    TriggerPriority,
)


class MockTrigger(BaseTrigger):
    name = "mock"
    priority = TriggerPriority.NORMAL

    def __init__(self):
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True
        # Don't loop — just mark as started
        while self.started:
            await asyncio.sleep(0.1)

    async def stop(self):
        self.started = False
        self.stopped = True


@pytest.fixture(autouse=True)
def reset_manager():
    """Reset TriggerManager state between tests."""
    TriggerManager._registry.clear()
    TriggerManager._last_trigger_time = 0.0
    TriggerManager._running = False
    TriggerManager._cooldown = 0.1  # Short cooldown for tests
    yield


def test_register():
    trigger = MockTrigger()
    TriggerManager.register(trigger)
    assert "mock" in TriggerManager.get_registered()


@pytest.mark.asyncio
async def test_cooldown():
    from jarvis.core.event_bus import EventBus
    bus = EventBus()

    received = []

    async def handler(event, data):
        received.append(data)

    await bus.subscribe("trigger.mock", handler)

    # Monkey-patch the event_bus import
    import jarvis.core.trigger_manager as tm
    original_bus = tm.event_bus
    tm.event_bus = bus

    TriggerManager.set_cooldown(0.5)

    event1 = TriggerEvent(source="mock", priority=TriggerPriority.NORMAL)
    event2 = TriggerEvent(source="mock", priority=TriggerPriority.NORMAL)

    await TriggerManager.handle_trigger(event1)
    await TriggerManager.handle_trigger(event2)  # Should be suppressed

    assert len(received) == 1

    # Wait for cooldown
    await asyncio.sleep(0.6)
    await TriggerManager.handle_trigger(event2)
    assert len(received) == 2

    tm.event_bus = original_bus
