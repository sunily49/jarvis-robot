"""
Face Presence Trigger — lightweight OpenCV Haar cascade on Pi.

Detects face presence only (not identity). Identity is offloaded to server.
~8% CPU at 2-3 FPS on Pi 5.

Uses the shared camera_controller instead of opening its own VideoCapture,
so the camera device is never opened twice simultaneously.
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from jarvis.config import settings
from jarvis.core.trigger_manager import BaseTrigger, TriggerPriority

logger = logging.getLogger(__name__)

_HAAR_CASCADE = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"


class FaceTrigger(BaseTrigger):
    name = "face"
    priority = TriggerPriority.NORMAL

    def __init__(self) -> None:
        self._running = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="face")
        self._cascade = None
        self._face_present = False
        self._last_face_time = 0.0
        self._cooldown = 10.0  # Don't re-trigger for 10s after a face trigger

    async def start(self) -> None:
        from jarvis.vision.camera_controller import camera_controller

        self._cascade = cv2.CascadeClassifier(_HAAR_CASCADE)

        # Wait up to 10s for camera_controller to open the camera
        for _ in range(10):
            if camera_controller._cap and camera_controller._cap.isOpened():
                break
            await asyncio.sleep(1)
        else:
            logger.error("Camera not ready for face trigger — retrying in 30s")
            await asyncio.sleep(30)
            return

        self._running = True
        logger.info("Face trigger started (shared camera)")

        loop = asyncio.get_event_loop()

        while self._running:
            try:
                frame = await camera_controller.capture_frame_raw()
                if frame is None:
                    await asyncio.sleep(0.5)
                    continue

                faces = await loop.run_in_executor(
                    self._executor, self._detect_faces_in_frame, frame
                )
                now = time.time()

                if faces is not None and len(faces) > 0:
                    if not self._face_present and (now - self._last_face_time > self._cooldown):
                        self._face_present = True
                        self._last_face_time = now
                        logger.info("Face detected (%d face(s))", len(faces))
                        await self.fire(
                            confidence=0.8,
                            data={"face_count": len(faces)},
                        )
                        await self._try_identify(frame)
                else:
                    self._face_present = False

                # ~3 FPS
                await asyncio.sleep(0.33)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Face trigger error")
                await asyncio.sleep(1.0)

    def _detect_faces_in_frame(self, frame: np.ndarray) -> np.ndarray | None:
        """Blocking face detection on a pre-captured frame (runs in thread)."""
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            return self._cascade.detectMultiScale(
                gray,
                scaleFactor=1.2,
                minNeighbors=5,
                minSize=(60, 60),
            )
        except Exception:
            return None

    async def _try_identify(self, frame: np.ndarray) -> None:
        """Send face crop to server for identification if available."""
        if not settings.VISION_FACE_RECOGNITION:
            return
        try:
            from jarvis.core.server_client import server_client
            if not server_client.server_available:
                return
            _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            result = await server_client.identify_face(jpeg.tobytes())
            if result and result.get("name"):
                name = result["name"]
                from jarvis.core.event_bus import event_bus
                await event_bus.publish("face.identified", {
                    "name": name,
                    "confidence": result.get("confidence", 0),
                })
                await server_client.record_encounter(name)
                person = await server_client.get_person(name)
                greeting = f"Hello {name}!"
                if person and person.get("preferences", {}).get("greeting"):
                    greeting = person["preferences"]["greeting"]
                from jarvis.audio.tts import tts
                await tts.announce(greeting)
                logger.info("Face identified: %s (encounters: %s)",
                            name, person.get("encounter_count") if person else "?")
        except Exception:
            logger.debug("Face identification failed (server may be offline)")

    async def stop(self) -> None:
        self._running = False
        self._executor.shutdown(wait=False)
        logger.info("Face trigger stopped")


if settings.TRIGGER_FACE:
    from jarvis.core.trigger_manager import TriggerManager
    TriggerManager.register(FaceTrigger())
