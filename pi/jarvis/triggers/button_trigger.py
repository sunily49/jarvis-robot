"""
Push Button Trigger — GPIO edge detection with hardware debounce.

Most reliable trigger — works even when audio/camera fail.
Priority: CRITICAL.

Supports Pi 1–4 via RPi.GPIO and Pi 5 via gpiozero (lgpio backend).
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
        """Blocking GPIO listener — tries RPi.GPIO first, falls back to gpiozero on Pi 5."""
        if self._listen_rpigpio():
            return
        if self._listen_gpiozero():
            return
        logger.warning("No GPIO library worked — button trigger disabled")

    def _listen_rpigpio(self) -> bool:
        """Try RPi.GPIO edge detection. Returns True if it ran (even if it errored)."""
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(settings.GPIO_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            logger.debug("Button GPIO using RPi.GPIO")

            while self._running:
                channel = GPIO.wait_for_edge(
                    settings.GPIO_BUTTON_PIN,
                    GPIO.FALLING,
                    timeout=1000,   # 1s timeout to recheck _running
                    bouncetime=50,  # 50ms debounce
                )
                if channel is not None:
                    self._event.set()

            GPIO.cleanup(settings.GPIO_BUTTON_PIN)
            return True

        except ImportError:
            return False  # Not installed — try gpiozero
        except RuntimeError as e:
            if "SOC peripheral" in str(e) or "peripheral base" in str(e).lower():
                logger.info("RPi.GPIO not supported on this hardware — trying gpiozero")
                return False  # Pi 5 — try gpiozero
            logger.exception("Button RPi.GPIO error")
            return True  # Ran but failed for another reason — don't retry
        except Exception:
            logger.exception("Button RPi.GPIO error")
            return True

    def _listen_gpiozero(self) -> bool:
        """Try gpiozero edge detection (Pi 5 / lgpio backend). Returns True if it ran."""
        try:
            from gpiozero import Button
            logger.debug("Button GPIO using gpiozero")

            btn = Button(settings.GPIO_BUTTON_PIN, pull_up=True, bounce_time=0.05)

            while self._running:
                pressed = btn.wait_for_press(timeout=1)
                if pressed and self._running:
                    self._event.set()

            btn.close()
            return True

        except ImportError:
            return False
        except Exception:
            logger.exception("Button gpiozero error")
            return True

    async def stop(self) -> None:
        self._running = False
        self._event.set()  # Unblock the wait
        self._executor.shutdown(wait=False)
        logger.info("Button trigger stopped")


if settings.TRIGGER_BUTTON:
    from jarvis.core.trigger_manager import TriggerManager
    TriggerManager.register(ButtonTrigger())
