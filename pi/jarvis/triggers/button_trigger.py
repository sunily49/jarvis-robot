"""
Push Button Trigger — GPIO edge detection with hardware debounce.

Most reliable trigger — works even when audio/camera fail.
Priority: CRITICAL.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from jarvis.config import settings
from jarvis.core.trigger_manager import BaseTrigger, TriggerPriority

logger = logging.getLogger(__name__)


class ButtonTrigger(BaseTrigger):
    name = "button"
    priority = TriggerPriority.CRITICAL

    def __init__(self) -> None:
        self._running = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="button")
        self._event = asyncio.Event()

    async def start(self) -> None:
        self._running = True
        loop = asyncio.get_event_loop()
        loop.run_in_executor(self._executor, self._gpio_listen)
        logger.info("Button trigger started on GPIO pin %d", settings.GPIO_BUTTON_PIN)

        while self._running:
            await self._event.wait()
            self._event.clear()
            if self._running:
                logger.info("Button pressed!")
                await self.fire(confidence=1.0)

    def _gpio_listen(self) -> None:
        """Blocking GPIO listener in thread."""
        try:
            import RPi.GPIO as GPIO

            GPIO.setmode(GPIO.BCM)
            GPIO.setup(settings.GPIO_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

            while self._running:
                # Wait for falling edge (button press) with debounce
                channel = GPIO.wait_for_edge(
                    settings.GPIO_BUTTON_PIN,
                    GPIO.FALLING,
                    timeout=1000,  # 1s timeout to check _running
                    bouncetime=50,  # 50ms debounce
                )
                if channel is not None:
                    self._event.set()

        except ImportError:
            logger.warning("RPi.GPIO not available — button trigger disabled (not on Pi?)")
            return
        except Exception:
            logger.exception("Button GPIO error")

    async def stop(self) -> None:
        self._running = False
        self._event.set()  # Unblock the wait
        self._executor.shutdown(wait=False)
        try:
            import RPi.GPIO as GPIO
            GPIO.cleanup(settings.GPIO_BUTTON_PIN)
        except (ImportError, RuntimeError):
            pass
        logger.info("Button trigger stopped")


if settings.TRIGGER_BUTTON:
    from jarvis.core.trigger_manager import TriggerManager
    TriggerManager.register(ButtonTrigger())
