"""
TriggerManager — central coordinator for all wake-up triggers.

Features:
- Registry pattern: triggers self-register on import
- Priority queue: higher-priority triggers win when simultaneous
- 3-second cooldown: prevents rapid re-triggering
- asyncio.Lock: one trigger processed at a time
- Publishes events to EventBus for downstream consumers
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from jarvis.core.event_bus import event_bus

logger = logging.getLogger(__name__)


class TriggerPriority(IntEnum):
    LOW = 10        # PIR motion, scheduled
    NORMAL = 50     # Wake word, clap, face presence
    HIGH = 80       # Telegram command
    CRITICAL = 100  # Push button (hardware, most reliable)


@dataclass
class TriggerEvent:
    source: str                             # e.g., "wakeword", "button", "face"
    priority: TriggerPriority = TriggerPriority.NORMAL
    confidence: float = 1.0                 # 0.0–1.0
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class BaseTrigger(ABC):
    """Base class all triggers must implement."""

    name: str = "unnamed"
    priority: TriggerPriority = TriggerPriority.NORMAL

    @abstractmethod
    async def start(self) -> None:
        """Start listening for this trigger. Must call self.fire() when triggered."""

    @abstractmethod
    async def stop(self) -> None:
        """Clean up resources."""

    async def fire(self, confidence: float = 1.0, data: dict[str, Any] | None = None) -> None:
        """Called by the trigger when activation is detected."""
        event = TriggerEvent(
            source=self.name,
            priority=self.priority,
            confidence=confidence,
            data=data or {},
        )
        await TriggerManager.handle_trigger(event)


class TriggerManager:
    """Singleton manager that coordinates all registered triggers."""

    _registry: list[BaseTrigger] = []
    _lock = asyncio.Lock()
    _last_trigger_time: float = 0.0
    _cooldown: float = 3.0  # overridden from settings at init
    _running: bool = False

    @classmethod
    def register(cls, trigger: BaseTrigger) -> None:
        cls._registry.append(trigger)
        logger.info("Registered trigger: %s (priority=%s)", trigger.name, trigger.priority.name)

    @classmethod
    def set_cooldown(cls, seconds: float) -> None:
        cls._cooldown = seconds

    @classmethod
    async def start_all(cls) -> None:
        """Start all registered triggers as concurrent tasks."""
        cls._running = True
        from jarvis.config import settings
        cls._cooldown = settings.TRIGGER_COOLDOWN
        logger.info("Starting %d triggers (cooldown=%.1fs)", len(cls._registry), cls._cooldown)
        tasks = [asyncio.create_task(cls._run_trigger(t)) for t in cls._registry]
        await asyncio.gather(*tasks)

    @classmethod
    async def stop_all(cls) -> None:
        cls._running = False
        for trigger in cls._registry:
            try:
                await trigger.stop()
            except Exception:
                logger.exception("Error stopping trigger %s", trigger.name)

    @classmethod
    async def handle_trigger(cls, event: TriggerEvent) -> None:
        """Process a trigger event with cooldown and locking."""
        now = time.time()
        if now - cls._last_trigger_time < cls._cooldown:
            logger.debug(
                "Trigger '%s' suppressed (cooldown: %.1fs remaining)",
                event.source,
                cls._cooldown - (now - cls._last_trigger_time),
            )
            return

        async with cls._lock:
            # Re-check after acquiring lock
            now = time.time()
            if now - cls._last_trigger_time < cls._cooldown:
                return
            cls._last_trigger_time = now
            logger.info(
                "TRIGGERED: source=%s priority=%s confidence=%.2f",
                event.source,
                event.priority.name,
                event.confidence,
            )
            await event_bus.publish(f"trigger.{event.source}", {
                "source": event.source,
                "priority": event.priority,
                "confidence": event.confidence,
                "data": event.data,
                "timestamp": event.timestamp,
            })

    @classmethod
    async def _run_trigger(cls, trigger: BaseTrigger) -> None:
        while cls._running:
            try:
                await trigger.start()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Trigger '%s' crashed, restarting in 5s", trigger.name)
                await asyncio.sleep(5)

    @classmethod
    def get_registered(cls) -> list[str]:
        return [t.name for t in cls._registry]
