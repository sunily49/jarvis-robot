"""
PIR Motion Trigger — HC-SR501 GPIO motion sensor.

Low CPU (<0.1%), detects movement in room. Good for auto-wake in reception/smart home.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from jarvis.config import settings
from jarvis.core.trigger_manager import BaseTrigger, TriggerPriority

logger = logging.getLogger(__name__)


class PIRTrigger(BaseTrigger):
    name = "pir"
    priority = TriggerPriority.LOW

    def __init__(self) -> None:
        self._running = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pir")
        self._event = asyncio.Event()

    async def start(self) -> None:
        self._running = True
        loop = asyncio.get_event_loop()
        loop.run_in_executor(self._executor, self._gpio_listen)
        logger.info("PIR trigger started on GPIO pin %d", settings.GPIO_PIR_PIN)

        while self._running:
            await self._event.wait()
            self._event.clear()
            if self._running:
                logger.info("PIR motion detected")
                await self.fire(confidence=0.6, data={"sensor": "pir"})
                # PIR sensors have their own hardware cooldown (~2-3s),
                # but add software cooldown too
                await asyncio.sleep(5.0)

    def _gpio_listen(self) -> None:
        try:
            import RPi.GPIO as GPIO

            GPIO.setmode(GPIO.BCM)
            GPIO.setup(settings.GPIO_PIR_PIN, GPIO.IN)

            while self._running:
                channel = GPIO.wait_for_edge(
                    settings.GPIO_PIR_PIN,
                    GPIO.RISING,
                    timeout=1000,
                )
                if channel is not None:
                    self._event.set()

        except ImportError:
            logger.warning("RPi.GPIO not available — PIR trigger disabled")
            return
        except Exception:
            logger.exception("PIR GPIO error")

    async def stop(self) -> None:
        self._running = False
        self._event.set()
        self._executor.shutdown(wait=False)
        try:
            import RPi.GPIO as GPIO
            GPIO.cleanup(settings.GPIO_PIR_PIN)
        except (ImportError, RuntimeError):
            pass
        logger.info("PIR trigger stopped")


if settings.TRIGGER_PIR:
    from jarvis.core.trigger_manager import TriggerManager
    TriggerManager.register(PIRTrigger())
