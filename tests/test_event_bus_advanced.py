"""Advanced EventBus tests — concurrent publish, multiple subscribers, edge cases."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "pi"))


@pytest.fixture
def bus():
    from jarvis.core.event_bus import EventBus
    return EventBus()


@pytest.mark.asyncio
async def test_multiple_subscribers_same_pattern(bus):
    results = []

    async def handler_a(event, data):
        results.append("A")

    async def handler_b(event, data):
        results.append("B")

    await bus.subscribe("test.event", handler_a)
    await bus.subscribe("test.event", handler_b)
    await bus.publish("test.event", {})

    assert "A" in results
    assert "B" in results


@pytest.mark.asyncio
async def test_no_data_defaults_to_empty_dict(bus):
    received = []

    async def handler(event, data):
        received.append(data)

    await bus.subscribe("test", handler)
    await bus.publish("test")  # no data arg
    assert received[0] == {}


@pytest.mark.asyncio
async def test_event_data_passed_correctly(bus):
    received = []

    async def handler(event, data):
        received.append(data)

    await bus.subscribe("test", handler)
    await bus.publish("test", {"key": "value", "num": 42})
    assert received[0]["key"] == "value"
    assert received[0]["num"] == 42


@pytest.mark.asyncio
async def test_no_subscribers_no_error(bus):
    # Should not raise
    await bus.publish("orphan.event", {"data": 1})


@pytest.mark.asyncio
async def test_publish_to_multiple_patterns(bus):
    received = []

    async def handler(event, data):
        received.append(event)

    await bus.subscribe("a.*", handler)
    await bus.subscribe("b.*", handler)

    await bus.publish("a.one", {})
    await bus.publish("b.two", {})
    await bus.publish("c.three", {})  # should not match

    assert "a.one" in received
    assert "b.two" in received
    assert "c.three" not in received


@pytest.mark.asyncio
async def test_concurrent_publishes(bus):
    received = []

    async def handler(event, data):
        await asyncio.sleep(0.01)
        received.append(data["n"])

    await bus.subscribe("concurrent.*", handler)

    await asyncio.gather(
        bus.publish("concurrent.a", {"n": 1}),
        bus.publish("concurrent.b", {"n": 2}),
        bus.publish("concurrent.c", {"n": 3}),
    )

    assert sorted(received) == [1, 2, 3]


@pytest.mark.asyncio
async def test_unsubscribe_specific_removes_only_that(bus):
    results = []

    async def h1(event, data): results.append("h1")
    async def h2(event, data): results.append("h2")

    sid1 = await bus.subscribe("evt", h1)
    await bus.subscribe("evt", h2)

    await bus.unsubscribe(sid1)
    await bus.publish("evt", {})

    assert "h1" not in results
    assert "h2" in results


@pytest.mark.asyncio
async def test_resubscribe_after_unsubscribe(bus):
    results = []

    async def handler(event, data):
        results.append(event)

    sid = await bus.subscribe("test", handler)
    await bus.unsubscribe(sid)
    await bus.subscribe("test", handler)

    await bus.publish("test", {})
    assert len(results) == 1


@pytest.mark.asyncio
async def test_handler_exception_does_not_stop_others(bus):
    results = []

    async def bad(event, data):
        raise ValueError("boom")

    async def good(event, data):
        results.append("good")

    await bus.subscribe("test", bad)
    await bus.subscribe("test", good)
    await bus.publish("test", {})

    assert "good" in results


@pytest.mark.asyncio
async def test_wildcard_deep_pattern(bus):
    received = []

    async def handler(event, data):
        received.append(event)

    await bus.subscribe("sensor.*", handler)
    await bus.publish("sensor.temp", {})
    await bus.publish("sensor.humidity", {})
    await bus.publish("trigger.button", {})  # should not match

    assert "sensor.temp" in received
    assert "sensor.humidity" in received
    assert "trigger.button" not in received
