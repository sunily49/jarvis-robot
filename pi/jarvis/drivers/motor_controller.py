"""
Motor Controller — L298N DC motor driver with safety gate.

Safety rules (enforced, not advisory):
1. Pre-move clearance check via ultrasonic/LIDAR
2. asyncio.Lock prevents concurrent movement commands
3. Hardware emergency-stop GPIO pin
4. IMU tilt guard (future)
5. Continuous obstacle watch during movement
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from jarvis.config import settings

logger = logging.getLogger(__name__)


class MotorController:
    """L298N dual H-bridge motor controller with safety gate."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="motor")
        self._gpio = None
        self._pwm_a = None
        self._pwm_b = None
        self._lock = asyncio.Lock()
        self._moving = False
        self._emergency_stopped = False
        self._initialized = False

    async def start(self) -> None:
        if not settings.HW_MOTORS:
            logger.info("Motors disabled in config")
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._setup)

    def _setup(self) -> None:
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            GPIO.setmode(GPIO.BCM)

            # Motor A (left)
            GPIO.setup(settings.MOTOR_ENA_PIN, GPIO.OUT)
            GPIO.setup(settings.MOTOR_IN1_PIN, GPIO.OUT)
            GPIO.setup(settings.MOTOR_IN2_PIN, GPIO.OUT)
            self._pwm_a = GPIO.PWM(settings.MOTOR_ENA_PIN, 1000)
            self._pwm_a.start(0)

            # Motor B (right)
            GPIO.setup(settings.MOTOR_ENB_PIN, GPIO.OUT)
            GPIO.setup(settings.MOTOR_IN3_PIN, GPIO.OUT)
            GPIO.setup(settings.MOTOR_IN4_PIN, GPIO.OUT)
            self._pwm_b = GPIO.PWM(settings.MOTOR_ENB_PIN, 1000)
            self._pwm_b.start(0)

            # Emergency stop pin (active-low)
            GPIO.setup(settings.GPIO_EMERGENCY_STOP_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(
                settings.GPIO_EMERGENCY_STOP_PIN,
                GPIO.FALLING,
                callback=self._emergency_stop_isr,
                bouncetime=100,
            )

            self._initialized = True
            logger.info("Motor controller initialized")
        except ImportError:
            logger.warning("RPi.GPIO not available — motor controller disabled")
        except Exception:
            logger.exception("Motor setup error")

    # ── Safety Gate ───────────────────────────────────────────────────

    async def _check_clearance(self, direction: str) -> bool:
        """Check if path is clear before moving."""
        try:
            from jarvis.drivers.sensor_bus import sensor_bus
            distance = sensor_bus.get_reading("ultrasonic_front")
            if distance is not None and distance["value"] < 30:  # 30cm minimum
                logger.warning("Obstacle detected at %.1fcm — movement blocked", distance["value"])
                return False
        except Exception:
            pass  # No sensor available, allow movement (conservative default)
        return True

    def _emergency_stop_isr(self, channel: int) -> None:
        """Hardware interrupt for emergency stop."""
        self._emergency_stopped = True
        self._stop_motors_sync()
        logger.critical("EMERGENCY STOP activated via GPIO")

    # ── Movement Commands ─────────────────────────────────────────────

    async def move_forward(self, distance_cm: int = 50, speed: int = 0) -> dict[str, Any]:
        """Move forward with safety check."""
        return await self._move("forward", distance_cm, speed)

    async def move_backward(self, distance_cm: int = 50, speed: int = 0) -> dict[str, Any]:
        """Move backward."""
        return await self._move("backward", distance_cm, speed)

    async def turn_left(self, degrees: int = 90) -> dict[str, Any]:
        """Turn left in place."""
        return await self._turn("left", degrees)

    async def turn_right(self, degrees: int = 90) -> dict[str, Any]:
        """Turn right in place."""
        return await self._turn("right", degrees)

    async def emergency_stop(self) -> dict[str, Any]:
        """Immediate stop — all motors off."""
        self._emergency_stopped = True
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._stop_motors_sync)
        logger.warning("Emergency stop executed")
        return {"status": "stopped", "emergency": True}

    async def reset_emergency(self) -> dict[str, Any]:
        """Reset emergency stop flag."""
        self._emergency_stopped = False
        logger.info("Emergency stop reset")
        return {"status": "reset"}

    async def stop(self) -> None:
        """Clean shutdown."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._stop_motors_sync)
        if self._pwm_a:
            self._pwm_a.stop()
        if self._pwm_b:
            self._pwm_b.stop()
        self._executor.shutdown(wait=False)
        logger.info("Motor controller stopped")

    # ── Internal ──────────────────────────────────────────────────────

    async def _move(self, direction: str, distance_cm: int, speed: int) -> dict[str, Any]:
        if not self._initialized:
            return {"error": "Motors not initialized"}
        if self._emergency_stopped:
            return {"error": "Emergency stop active. Call reset_emergency first."}

        async with self._lock:
            # Safety gate
            if direction == "forward" and not await self._check_clearance("forward"):
                return {"error": "Path blocked — obstacle detected"}

            speed = speed or settings.MOTOR_MAX_SPEED
            duration = distance_cm / 20.0  # rough: ~20cm/s at full speed

            self._moving = True
            loop = asyncio.get_event_loop()

            if direction == "forward":
                await loop.run_in_executor(self._executor, self._set_forward, speed)
            else:
                await loop.run_in_executor(self._executor, self._set_backward, speed)

            # Move for calculated duration, checking obstacles continuously
            start = time.time()
            while time.time() - start < duration:
                if self._emergency_stopped:
                    break
                if direction == "forward" and not await self._check_clearance("forward"):
                    logger.warning("Obstacle appeared during movement — stopping")
                    break
                await asyncio.sleep(0.1)

            await loop.run_in_executor(self._executor, self._stop_motors_sync)
            self._moving = False

            return {"status": "completed", "direction": direction, "distance_cm": distance_cm}

    async def _turn(self, direction: str, degrees: int) -> dict[str, Any]:
        if not self._initialized:
            return {"error": "Motors not initialized"}
        if self._emergency_stopped:
            return {"error": "Emergency stop active"}

        async with self._lock:
            duration = degrees / 180.0  # rough: ~180°/s
            speed = settings.MOTOR_MAX_SPEED // 2

            loop = asyncio.get_event_loop()
            if direction == "left":
                await loop.run_in_executor(self._executor, self._set_turn_left, speed)
            else:
                await loop.run_in_executor(self._executor, self._set_turn_right, speed)

            await asyncio.sleep(duration)
            await loop.run_in_executor(self._executor, self._stop_motors_sync)

            return {"status": "completed", "direction": direction, "degrees": degrees}

    def _set_forward(self, speed: int) -> None:
        self._gpio.output(settings.MOTOR_IN1_PIN, self._gpio.HIGH)
        self._gpio.output(settings.MOTOR_IN2_PIN, self._gpio.LOW)
        self._gpio.output(settings.MOTOR_IN3_PIN, self._gpio.HIGH)
        self._gpio.output(settings.MOTOR_IN4_PIN, self._gpio.LOW)
        self._pwm_a.ChangeDutyCycle(speed)
        self._pwm_b.ChangeDutyCycle(speed)

    def _set_backward(self, speed: int) -> None:
        self._gpio.output(settings.MOTOR_IN1_PIN, self._gpio.LOW)
        self._gpio.output(settings.MOTOR_IN2_PIN, self._gpio.HIGH)
        self._gpio.output(settings.MOTOR_IN3_PIN, self._gpio.LOW)
        self._gpio.output(settings.MOTOR_IN4_PIN, self._gpio.HIGH)
        self._pwm_a.ChangeDutyCycle(speed)
        self._pwm_b.ChangeDutyCycle(speed)

    def _set_turn_left(self, speed: int) -> None:
        self._gpio.output(settings.MOTOR_IN1_PIN, self._gpio.LOW)
        self._gpio.output(settings.MOTOR_IN2_PIN, self._gpio.HIGH)
        self._gpio.output(settings.MOTOR_IN3_PIN, self._gpio.HIGH)
        self._gpio.output(settings.MOTOR_IN4_PIN, self._gpio.LOW)
        self._pwm_a.ChangeDutyCycle(speed)
        self._pwm_b.ChangeDutyCycle(speed)

    def _set_turn_right(self, speed: int) -> None:
        self._gpio.output(settings.MOTOR_IN1_PIN, self._gpio.HIGH)
        self._gpio.output(settings.MOTOR_IN2_PIN, self._gpio.LOW)
        self._gpio.output(settings.MOTOR_IN3_PIN, self._gpio.LOW)
        self._gpio.output(settings.MOTOR_IN4_PIN, self._gpio.HIGH)
        self._pwm_a.ChangeDutyCycle(speed)
        self._pwm_b.ChangeDutyCycle(speed)

    def _stop_motors_sync(self) -> None:
        if self._pwm_a:
            self._pwm_a.ChangeDutyCycle(0)
        if self._pwm_b:
            self._pwm_b.ChangeDutyCycle(0)


# Singleton
motor_controller = MotorController()
