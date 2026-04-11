"""
Asyncio pub/sub event bus — typed events with wildcard support.

Usage:
    bus = EventBus()
    bus.subscribe("trigger.*", my_handler)
    await bus.publish("trigger.wakeword", {"confidence": 0.95})
"""

import asyncio
import fnmatch
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

EventHandler = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


@dataclass
class _Subscription:
    pattern: str
    handler: EventHandler
    id: int = field(default_factory=lambda: id(object()))


class EventBus:
    """Process-wide async event bus with glob-pattern subscriptions."""

    def __init__(self) -> None:
        self._subscriptions: list[_Subscription] = []
        self._lock = asyncio.Lock()

    async def subscribe(self, pattern: str, handler: EventHandler) -> int:
        """Subscribe to events matching a glob pattern. Returns subscription ID."""
        sub = _Subscription(pattern=pattern, handler=handler)
        async with self._lock:
            self._subscriptions.append(sub)
        logger.debug("Subscribed %s to pattern '%s'", handler.__name__, pattern)
        return sub.id

    async def unsubscribe(self, sub_id: int) -> None:
        """Remove a subscription by ID."""
        async with self._lock:
            self._subscriptions = [s for s in self._subscriptions if s.id != sub_id]

    async def publish(self, event: str, data: dict[str, Any] | None = None) -> None:
        """Publish an event to all matching subscribers. Non-blocking fan-out."""
        data = data or {}
        matching = [s for s in self._subscriptions if fnmatch.fnmatch(event, s.pattern)]
        if not matching:
            return
        logger.debug("Publishing '%s' to %d handlers", event, len(matching))
        tasks = [self._safe_call(s.handler, event, data) for s in matching]
        await asyncio.gather(*tasks)

    @staticmethod
    async def _safe_call(
        handler: EventHandler, event: str, data: dict[str, Any]
    ) -> None:
        try:
            await handler(event, data)
        except Exception:
            logger.exception("Handler %s failed on event '%s'", handler.__name__, event)


# Singleton instance — import and use directly
event_bus = EventBus()
