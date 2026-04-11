"""Tests for EventBus pub/sub system."""

import asyncio
import pytest


@pytest.fixture
def event_bus():
    from jarvis.core.event_bus import EventBus
    return EventBus()


@pytest.mark.asyncio
async def test_publish_subscribe(event_bus):
    received = []

    async def handler(event, data):
        received.append((event, data))

    await event_bus.subscribe("test.event", handler)
    await event_bus.publish("test.event", {"key": "value"})

    assert len(received) == 1
    assert received[0][0] == "test.event"
    assert received[0][1]["key"] == "value"


@pytest.mark.asyncio
async def test_wildcard_pattern(event_bus):
    received = []

    async def handler(event, data):
        received.append(event)

    await event_bus.subscribe("trigger.*", handler)
    await event_bus.publish("trigger.wakeword", {})
    await event_bus.publish("trigger.button", {})
    await event_bus.publish("session.started", {})  # Should not match

    assert len(received) == 2
    assert "trigger.wakeword" in received
    assert "trigger.button" in received


@pytest.mark.asyncio
async def test_unsubscribe(event_bus):
    received = []

    async def handler(event, data):
        received.append(event)

    sub_id = await event_bus.subscribe("test.*", handler)
    await event_bus.publish("test.one", {})
    assert len(received) == 1

    await event_bus.unsubscribe(sub_id)
    await event_bus.publish("test.two", {})
    assert len(received) == 1  # No new events


@pytest.mark.asyncio
async def test_handler_error_doesnt_crash(event_bus):
    async def bad_handler(event, data):
        raise RuntimeError("oops")

    async def good_handler(event, data):
        pass

    await event_bus.subscribe("test", bad_handler)
    await event_bus.subscribe("test", good_handler)

    # Should not raise
    await event_bus.publish("test", {})
