"""
Camera Controller — PTZ pan/tilt via v4l2-ctl, frame capture for server offloading.

Provides: pan_to, scan_environment (360° sweep), capture_frame.
The EMEET PIXY PTZ camera is controlled via USB UVC pan/tilt commands.
"""

import asyncio
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from jarvis.config import settings

logger = logging.getLogger(__name__)

# EMEET PIXY pan range: typically -36000 to 36000 (in 1/3600 degree units)
PAN_MIN = -36000
PAN_MAX = 36000
TILT_MIN = -36000
TILT_MAX = 36000
SCAN_STEPS = 8  # 360° / 8 = 45° per step


class CameraController:
    """Controls PTZ camera and provides frame capture."""

    def __init__(self) -> None:
        self._cap: cv2.VideoCapture | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="camera")
        self._lock = asyncio.Lock()
        self._current_pan = 0
        self._current_tilt = 0

    async def start(self) -> None:
        device = self._find_camera()
        if device is None:
            logger.error("No camera found (tried %s and /dev/video0–4)", settings.CAMERA_DEVICE)
            return
        self._cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.CAMERA_FRAME_WIDTH)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.CAMERA_FRAME_HEIGHT)
        if not self._cap.isOpened():
            logger.error("Camera not available at %s", device)
            return
        logger.info("Camera controller started (%s)", device)

    @staticmethod
    def _find_camera() -> str | None:
        """Try the configured device, then scan /dev/video0–4 for the first working camera."""
        candidates = [settings.CAMERA_DEVICE] + [f"/dev/video{i}" for i in [0, 1, 2, 4, 10, 19, 20]]
        seen = set()
        for dev in candidates:
            if dev in seen:
                continue
            seen.add(dev)
            cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                ret, _ = cap.read()
                cap.release()
                if ret:
                    return dev
            else:
                cap.release()
        return None

    async def stop(self) -> None:
        if self._cap:
            self._cap.release()
        self._executor.shutdown(wait=False)
        logger.info("Camera controller stopped")

    async def capture_frame(self) -> bytes | None:
        """Capture a single JPEG frame."""
        async with self._lock:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(self._executor, self._capture_jpeg)

    def _capture_jpeg(self) -> bytes | None:
        if not self._cap or not self._cap.isOpened():
            return None
        ret, frame = self._cap.read()
        if not ret:
            return None
        _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return jpeg.tobytes()

    async def capture_frame_raw(self) -> np.ndarray | None:
        """Capture a raw BGR frame (for local processing)."""
        async with self._lock:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(self._executor, self._capture_raw)

    def _capture_raw(self) -> np.ndarray | None:
        if not self._cap or not self._cap.isOpened():
            return None
        ret, frame = self._cap.read()
        return frame if ret else None

    # ── PTZ Control ───────────────────────────────────────────────────

    async def pan_to(self, angle: int) -> None:
        """Pan to absolute angle (in v4l2 units)."""
        angle = max(PAN_MIN, min(PAN_MAX, angle))
        await self._v4l2_set("pan_absolute", angle)
        self._current_pan = angle
        logger.debug("Pan to %d", angle)

    async def tilt_to(self, angle: int) -> None:
        """Tilt to absolute angle."""
        angle = max(TILT_MIN, min(TILT_MAX, angle))
        await self._v4l2_set("tilt_absolute", angle)
        self._current_tilt = angle
        logger.debug("Tilt to %d", angle)

    async def pan_relative(self, degrees: int) -> None:
        """Pan relative to current position (in degrees, converted to v4l2 units)."""
        units = degrees * 100  # rough conversion
        new_pan = max(PAN_MIN, min(PAN_MAX, self._current_pan + units))
        await self.pan_to(new_pan)

    async def look_at_direction(self, direction: str) -> None:
        """Pan to a named direction: left, right, center, behind."""
        directions = {
            "center": 0,
            "left": PAN_MIN // 2,
            "right": PAN_MAX // 2,
            "hard_left": PAN_MIN,
            "hard_right": PAN_MAX,
        }
        angle = directions.get(direction.lower(), 0)
        await self.pan_to(angle)

    async def scan_environment(self) -> list[bytes]:
        """360° scan: capture frame at each of 8 positions. Returns list of JPEGs."""
        frames: list[bytes] = []
        step_size = (PAN_MAX - PAN_MIN) // SCAN_STEPS

        for i in range(SCAN_STEPS):
            angle = PAN_MIN + (step_size * i)
            await self.pan_to(angle)
            await asyncio.sleep(0.5)  # Let camera settle
            frame = await self.capture_frame()
            if frame:
                frames.append(frame)

        # Return to center
        await self.pan_to(0)
        logger.info("Environment scan complete (%d frames)", len(frames))
        return frames

    @property
    def pan_position(self) -> int:
        return self._current_pan

    @property
    def tilt_position(self) -> int:
        return self._current_tilt

    # ── v4l2-ctl helper ───────────────────────────────────────────────

    async def _v4l2_set(self, control: str, value: int) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._v4l2_set_sync, control, value)

    def _v4l2_set_sync(self, control: str, value: int) -> None:
        try:
            subprocess.run(
                ["v4l2-ctl", "-d", settings.CAMERA_DEVICE, "-c", f"{control}={value}"],
                capture_output=True,
                timeout=5,
            )
        except FileNotFoundError:
            logger.warning("v4l2-ctl not found — PTZ control unavailable")
        except subprocess.TimeoutExpired:
            logger.warning("v4l2-ctl timed out for %s=%d", control, value)


# Singleton
camera_controller = CameraController()
