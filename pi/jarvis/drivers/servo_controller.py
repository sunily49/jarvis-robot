"""
Servo Controller — PCA9685 16-channel PWM servo board via I2C.

Used for: head pan/tilt, robotic arm joints, gripper.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from jarvis.config import settings

logger = logging.getLogger(__name__)


class ServoController:
    """PCA9685 16-channel servo controller."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="servo")
        self._pca = None
        self._initialized = False
        self._positions: dict[int, float] = {}  # channel → angle

    async def start(self) -> None:
        if not settings.HW_SERVOS:
            logger.info("Servos disabled in config")
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._setup)

    def _setup(self) -> None:
        try:
            import board
            import busio
            from adafruit_pca9685 import PCA9685
            from adafruit_motor import servo

            i2c = busio.I2C(board.SCL, board.SDA)
            self._pca = PCA9685(i2c)
            self._pca.frequency = 50  # Standard servo frequency
            self._initialized = True
            logger.info("Servo controller initialized (PCA9685, 16 channels)")
        except ImportError:
            logger.warning("Adafruit PCA9685 libs not available — servo controller disabled")
        except Exception:
            logger.exception("Servo setup error")

    async def set_angle(self, channel: int, angle: float) -> dict[str, Any]:
        """Set servo angle (0-180 degrees) on a specific channel."""
        if not self._initialized:
            return {"error": "Servo controller not initialized"}
        if not 0 <= channel <= 15:
            return {"error": f"Channel {channel} out of range (0-15)"}
        angle = max(0, min(180, angle))

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._set_angle_sync, channel, angle)
        self._positions[channel] = angle
        return {"channel": channel, "angle": angle}

    def _set_angle_sync(self, channel: int, angle: float) -> None:
        from adafruit_motor import servo as servo_lib
        s = servo_lib.Servo(self._pca.channels[channel])
        s.angle = angle

    async def set_head_tilt(self, angle: float) -> dict[str, Any]:
        """Convenience: set head tilt servo (channel 0)."""
        return await self.set_angle(0, angle)

    async def set_head_pan(self, angle: float) -> dict[str, Any]:
        """Convenience: set head pan servo (channel 1)."""
        return await self.set_angle(1, angle)

    async def get_position(self, channel: int) -> float:
        return self._positions.get(channel, 90.0)

    async def stop(self) -> None:
        if self._pca:
            self._pca.deinit()
        self._executor.shutdown(wait=False)
        logger.info("Servo controller stopped")


# Singleton
servo_controller = ServoController()
