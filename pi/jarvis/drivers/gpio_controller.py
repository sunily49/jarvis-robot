"""
GPIO Controller — relay, light, switch, and PWM control.

Safety: electrical isolation via relay coils, fuse protection.
All high-voltage (230V AC) goes through relay contacts, never near Pi GPIO.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from jarvis.config import settings

logger = logging.getLogger(__name__)


class GPIOController:
    """Controls GPIO pins for relays, lights, and switches."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gpio")
        self._gpio = None
        self._relay_pins: list[int] = []
        self._relay_states: dict[int, bool] = {}
        self._pwm_channels: dict[int, Any] = {}
        self._initialized = False

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._setup)

    def _setup(self) -> None:
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            # Parse relay pins
            if settings.GPIO_RELAY_PINS:
                self._relay_pins = [
                    int(p.strip()) for p in settings.GPIO_RELAY_PINS.split(",") if p.strip()
                ]
                for pin in self._relay_pins:
                    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)  # Active-low relays
                    self._relay_states[pin] = False

            self._initialized = True
            logger.info("GPIO controller initialized (relays: %s)", self._relay_pins)
        except ImportError:
            logger.warning("RPi.GPIO not available — GPIO controller disabled")
        except Exception:
            logger.exception("GPIO setup error")

    async def control_relay(self, pin: int, state: bool) -> dict[str, Any]:
        """Turn a relay on/off. Returns status."""
        if not self._initialized:
            return {"error": "GPIO not initialized"}
        if pin not in self._relay_pins:
            return {"error": f"Pin {pin} is not a configured relay pin"}

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._set_relay, pin, state)
        self._relay_states[pin] = state
        logger.info("Relay pin %d set to %s", pin, "ON" if state else "OFF")
        return {"pin": pin, "state": "on" if state else "off"}

    def _set_relay(self, pin: int, state: bool) -> None:
        # Active-low relays: LOW = ON, HIGH = OFF
        self._gpio.output(pin, self._gpio.LOW if state else self._gpio.HIGH)

    async def control_light(self, room: str, state: bool) -> dict[str, Any]:
        """Control a light by room name (maps to relay pin)."""
        # Simple mapping — extend as needed
        room_map = {f"relay_{i}": pin for i, pin in enumerate(self._relay_pins)}
        pin = room_map.get(room)
        if pin is None:
            return {"error": f"Unknown room: {room}"}
        return await self.control_relay(pin, state)

    async def set_pwm(self, pin: int, duty_cycle: float, frequency: float = 1000) -> dict[str, Any]:
        """Set PWM on a pin (0-100 duty cycle)."""
        if not self._initialized:
            return {"error": "GPIO not initialized"}

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self._executor, self._set_pwm_sync, pin, duty_cycle, frequency
        )
        return {"pin": pin, "duty_cycle": duty_cycle, "frequency": frequency}

    def _set_pwm_sync(self, pin: int, duty_cycle: float, frequency: float) -> None:
        if pin not in self._pwm_channels:
            self._gpio.setup(pin, self._gpio.OUT)
            self._pwm_channels[pin] = self._gpio.PWM(pin, frequency)
            self._pwm_channels[pin].start(duty_cycle)
        else:
            self._pwm_channels[pin].ChangeDutyCycle(duty_cycle)

    async def read_pin(self, pin: int) -> dict[str, Any]:
        """Read a GPIO pin state."""
        if not self._initialized:
            return {"error": "GPIO not initialized"}
        loop = asyncio.get_event_loop()
        value = await loop.run_in_executor(self._executor, self._read_sync, pin)
        return {"pin": pin, "value": value}

    def _read_sync(self, pin: int) -> int:
        self._gpio.setup(pin, self._gpio.IN)
        return self._gpio.input(pin)

    async def get_relay_states(self) -> dict[int, bool]:
        return dict(self._relay_states)

    async def stop(self) -> None:
        for pwm in self._pwm_channels.values():
            pwm.stop()
        if self._gpio:
            # Only clean up our pins
            for pin in self._relay_pins:
                try:
                    self._gpio.cleanup(pin)
                except Exception:
                    pass
        self._executor.shutdown(wait=False)
        logger.info("GPIO controller stopped")


# Singleton
gpio_controller = GPIOController()
