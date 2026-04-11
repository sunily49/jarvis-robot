"""
Telegram Trigger — bot commands for remote wake-up and control.

Commands: /wake, /photo, /status, /stop
Only processes commands from allowed user IDs.
"""

import asyncio
import logging

from jarvis.config import settings
from jarvis.core.trigger_manager import BaseTrigger, TriggerPriority

logger = logging.getLogger(__name__)


class TelegramTrigger(BaseTrigger):
    name = "telegram"
    priority = TriggerPriority.HIGH

    def __init__(self) -> None:
        self._running = False
        self._app = None
        self._allowed_users: set[int] = set()

    async def start(self) -> None:
        from telegram import Update
        from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

        if not settings.TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN not set — telegram trigger disabled")
            return

        # Parse allowed user IDs
        if settings.TELEGRAM_ALLOWED_USERS:
            self._allowed_users = {
                int(uid.strip())
                for uid in settings.TELEGRAM_ALLOWED_USERS.split(",")
                if uid.strip()
            }

        self._app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

        # Register command handlers
        self._app.add_handler(CommandHandler("wake", self._cmd_wake))
        self._app.add_handler(CommandHandler("photo", self._cmd_photo))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("stop", self._cmd_stop))
        self._app.add_handler(CommandHandler("register", self._cmd_register))

        self._running = True
        logger.info("Telegram trigger started (allowed_users=%s)", self._allowed_users or "any")

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

        # Keep running
        while self._running:
            await asyncio.sleep(1.0)

    def _is_authorized(self, user_id: int) -> bool:
        if not self._allowed_users:
            return True  # No restriction
        return user_id in self._allowed_users

    async def _cmd_wake(self, update, context) -> None:
        """Remote wake-up command."""
        if not self._is_authorized(update.effective_user.id):
            await update.message.reply_text("Unauthorized.")
            return
        logger.info("Telegram /wake from user %d", update.effective_user.id)
        await self.fire(confidence=1.0, data={
            "command": "wake",
            "user_id": update.effective_user.id,
            "username": update.effective_user.first_name,
        })
        await update.message.reply_text("JARVIS activated!")

    async def _cmd_photo(self, update, context) -> None:
        """Send current camera frame."""
        if not self._is_authorized(update.effective_user.id):
            await update.message.reply_text("Unauthorized.")
            return
        try:
            import cv2
            cap = cv2.VideoCapture(settings.CAMERA_DEVICE)
            ret, frame = cap.read()
            cap.release()
            if ret:
                _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                from io import BytesIO
                buf = BytesIO(jpeg.tobytes())
                buf.name = "jarvis_photo.jpg"
                await update.message.reply_photo(photo=buf, caption="Current view")
            else:
                await update.message.reply_text("Camera unavailable.")
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_status(self, update, context) -> None:
        """Report system status."""
        if not self._is_authorized(update.effective_user.id):
            await update.message.reply_text("Unauthorized.")
            return
        from jarvis.core.trigger_manager import TriggerManager
        from jarvis.core.server_client import server_client
        triggers = TriggerManager.get_registered()
        lines = [
            "JARVIS Status:",
            f"  Triggers: {', '.join(triggers)}",
            f"  Server: {'online' if server_client.server_available else 'offline'}",
        ]
        await update.message.reply_text("\n".join(lines))

    async def _cmd_register(self, update, context) -> None:
        """Register a face: /register <name> (with a photo attached or camera capture)."""
        if not self._is_authorized(update.effective_user.id):
            await update.message.reply_text("Unauthorized.")
            return

        args = context.args
        if not args:
            await update.message.reply_text("Usage: /register <name>\nSend with a photo or I'll use the camera.")
            return

        name = " ".join(args)
        from jarvis.core.server_client import server_client
        if not server_client.server_available:
            await update.message.reply_text("Server offline — face registration requires server.")
            return

        jpeg_bytes = None
        # Check if a photo was sent with the command
        if update.message.photo:
            photo = update.message.photo[-1]  # highest resolution
            file = await photo.get_file()
            jpeg_bytes = await file.download_as_bytearray()
        else:
            # Use camera
            try:
                from jarvis.vision.camera_controller import camera_controller
                jpeg_bytes = await camera_controller.capture_frame()
            except Exception:
                await update.message.reply_text("Camera unavailable.")
                return

        if not jpeg_bytes:
            await update.message.reply_text("Could not get image.")
            return

        ok = await server_client.register_face(name, bytes(jpeg_bytes))
        if ok:
            await update.message.reply_text(f"Registered face: {name}")
        else:
            await update.message.reply_text("No face detected. Make sure the face is clearly visible.")

    async def _cmd_stop(self, update, context) -> None:
        """Stop active session."""
        if not self._is_authorized(update.effective_user.id):
            await update.message.reply_text("Unauthorized.")
            return
        from jarvis.core.event_bus import event_bus
        await event_bus.publish("session.force_stop", {})
        await update.message.reply_text("Session stopped.")

    async def stop(self) -> None:
        self._running = False
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        logger.info("Telegram trigger stopped")


if settings.TRIGGER_TELEGRAM:
    from jarvis.core.trigger_manager import TriggerManager
    TriggerManager.register(TelegramTrigger())
