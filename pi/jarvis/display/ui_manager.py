"""
UIManager — main display controller for the JARVIS HDMI robot face.

Runs pygame in a dedicated thread (via ThreadPoolExecutor) so the asyncio
main loop stays unblocked. Handles screen modes, EventBus integration,
idle timeout, and all rendering.
"""

import asyncio
import io
import platform
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from enum import Enum, auto
from queue import SimpleQueue
from typing import Any

import structlog

from jarvis.config import settings
from jarvis.core.event_bus import event_bus
from jarvis.display.face_renderer import (
    BG_COLOR,
    CYAN,
    DIM_WHITE,
    GREEN,
    ORANGE,
    RED,
    WHITE,
    YELLOW,
    Emotion,
    FaceRenderer,
)

log = structlog.get_logger(__name__)


# ── Screen Modes ─────────────────────────────────────────────────────
class ScreenMode(Enum):
    FACE = auto()
    STATUS = auto()
    CONVERSATION = auto()
    CAMERA = auto()
    SPLIT = auto()  # face left + status right


# ── Command types for cross-thread queue ─────────────────────────────
class _Cmd(Enum):
    SET_SCREEN = auto()
    SET_EMOTION = auto()
    SET_STATUS = auto()
    ADD_CONVERSATION = auto()
    SET_CAMERA_FRAME = auto()
    STOP = auto()


class UIManager:
    """Main display controller. Manages pygame in a background thread."""

    def __init__(self) -> None:
        self._width = settings.DISPLAY_WIDTH
        self._height = settings.DISPLAY_HEIGHT
        self._fps = settings.DISPLAY_FPS
        self._fullscreen = settings.DISPLAY_FULLSCREEN
        self._idle_timeout = settings.DISPLAY_IDLE_TIMEOUT

        self._queue: SimpleQueue[tuple[_Cmd, Any]] = SimpleQueue()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pygame")
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None

        # State (written from pygame thread only)
        self._screen_mode = ScreenMode.FACE
        self._face: FaceRenderer | None = None
        self._conversation: deque[tuple[str, str]] = deque(maxlen=20)
        self._camera_surface = None  # pygame.Surface or None
        self._server_status = "unknown"
        self._last_activity = time.time()
        self._idle = False
        self._sub_ids: list[int] = []

    # ── Public async API ─────────────────────────────────────────────

    async def start(self) -> None:
        """Initialize pygame in a background thread and subscribe to events."""
        self._loop = asyncio.get_running_loop()
        self._running = True
        self._loop.run_in_executor(self._executor, self._run_loop)
        await self._subscribe_events()
        log.info("ui_manager.started", width=self._width, height=self._height)

    async def stop(self) -> None:
        """Signal the pygame thread to quit and wait for cleanup."""
        self._queue.put((_Cmd.STOP, None))
        self._running = False
        await self._unsubscribe_events()
        self._executor.shutdown(wait=True)
        log.info("ui_manager.stopped")

    def set_screen(self, mode: ScreenMode) -> None:
        self._queue.put((_Cmd.SET_SCREEN, mode))
        self._touch_activity()

    def set_emotion(self, emotion: Emotion) -> None:
        self._queue.put((_Cmd.SET_EMOTION, emotion))
        self._touch_activity()

    def set_status(self, text: str, color: tuple = CYAN) -> None:
        self._queue.put((_Cmd.SET_STATUS, (text, color)))
        self._touch_activity()

    def add_conversation_line(self, role: str, text: str) -> None:
        self._queue.put((_Cmd.ADD_CONVERSATION, (role, text)))
        self._touch_activity()

    def set_camera_frame(self, jpeg_bytes: bytes) -> None:
        self._queue.put((_Cmd.SET_CAMERA_FRAME, jpeg_bytes))
        self._touch_activity()

    # ── EventBus subscriptions ───────────────────────────────────────

    async def _subscribe_events(self) -> None:
        sid = await event_bus.subscribe("session.state_changed", self._on_state_changed)
        self._sub_ids.append(sid)
        sid = await event_bus.subscribe("trigger.*", self._on_trigger)
        self._sub_ids.append(sid)
        sid = await event_bus.subscribe("session.transcript", self._on_transcript)
        self._sub_ids.append(sid)
        sid = await event_bus.subscribe("server.status_changed", self._on_server_status)
        self._sub_ids.append(sid)

    async def _unsubscribe_events(self) -> None:
        for sid in self._sub_ids:
            await event_bus.unsubscribe(sid)
        self._sub_ids.clear()

    async def _on_state_changed(self, _event: str, data: dict[str, Any]) -> None:
        state = data.get("state", "").upper()
        mapping = {
            "LISTENING": Emotion.LISTENING,
            "PROCESSING": Emotion.THINKING,
            "RESPONDING": Emotion.SPEAKING,
            "IDLE": Emotion.NEUTRAL,
        }
        emotion = mapping.get(state)
        if emotion:
            self.set_emotion(emotion)

    async def _on_trigger(self, event: str, data: dict[str, Any]) -> None:
        source = event.rsplit(".", 1)[-1] if "." in event else "unknown"
        self.set_emotion(Emotion.SURPRISED)
        self.set_status(f"Triggered: {source}", YELLOW)

    async def _on_transcript(self, _event: str, data: dict[str, Any]) -> None:
        role = data.get("role", "?")
        text = data.get("text", "")
        self.add_conversation_line(role, text)

    async def _on_server_status(self, _event: str, data: dict[str, Any]) -> None:
        status = data.get("status", "unknown")
        self._queue.put((_Cmd.SET_STATUS, (f"Server: {status}", GREEN if status == "connected" else RED)))
        self._server_status = status

    # ── Activity / idle tracking ─────────────────────────────────────

    def _touch_activity(self) -> None:
        self._last_activity = time.time()

    # ── Pygame thread ────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Blocking pygame loop — runs entirely in the executor thread."""
        import pygame  # import here so main thread doesn't need pygame at import time

        pygame.init()
        flags = pygame.FULLSCREEN if self._fullscreen else 0
        screen = pygame.display.set_mode((self._width, self._height), flags)
        pygame.display.set_caption("JARVIS")
        clock = pygame.time.Clock()
        self._face = FaceRenderer(self._width, self._height)

        # Preload font
        font_small = pygame.font.SysFont("monospace", 16)
        font_med = pygame.font.SysFont("monospace", 20)
        font_large = pygame.font.SysFont("monospace", 24, bold=True)

        start_time = time.time()

        while self._running:
            dt = clock.tick(self._fps) / 1000.0

            # Process command queue
            while not self._queue.empty():
                cmd, payload = self._queue.get_nowait()
                if cmd == _Cmd.STOP:
                    self._running = False
                    break
                elif cmd == _Cmd.SET_SCREEN:
                    self._screen_mode = payload
                elif cmd == _Cmd.SET_EMOTION:
                    self._face.set_emotion(payload)
                elif cmd == _Cmd.SET_STATUS:
                    text, color = payload
                    self._face.set_status(text, color)
                elif cmd == _Cmd.ADD_CONVERSATION:
                    self._conversation.append(payload)
                elif cmd == _Cmd.SET_CAMERA_FRAME:
                    try:
                        buf = io.BytesIO(payload)
                        self._camera_surface = pygame.image.load(buf)
                    except Exception:
                        log.warning("ui_manager.camera_frame_decode_failed")

            if not self._running:
                break

            # Handle pygame events
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self._running = False
                    break
                if ev.type == pygame.KEYDOWN:
                    self._touch_activity()
                    if ev.key == pygame.K_ESCAPE:
                        self._running = False
                    elif ev.key == pygame.K_F1:
                        self._screen_mode = ScreenMode.FACE
                    elif ev.key == pygame.K_F2:
                        self._screen_mode = ScreenMode.STATUS
                    elif ev.key == pygame.K_F3:
                        self._screen_mode = ScreenMode.CONVERSATION
                    elif ev.key == pygame.K_F4:
                        self._screen_mode = ScreenMode.CAMERA
                    elif ev.key == pygame.K_F5:
                        self._screen_mode = ScreenMode.SPLIT

            if not self._running:
                break

            # Idle timeout
            idle_elapsed = time.time() - self._last_activity
            was_idle = self._idle
            self._idle = idle_elapsed > self._idle_timeout
            if self._idle and not was_idle:
                self._face.set_emotion(Emotion.SLEEPING)
                log.info("ui_manager.idle_sleep", after_seconds=self._idle_timeout)
            elif not self._idle and was_idle:
                self._face.set_emotion(Emotion.NEUTRAL)
                log.info("ui_manager.idle_wake")

            # Update face animation
            self._face.update(dt)

            # Render active screen
            mode = self._screen_mode
            if mode == ScreenMode.FACE:
                self._face.render(screen)
            elif mode == ScreenMode.STATUS:
                self._render_status(screen, font_small, font_med, font_large, start_time)
            elif mode == ScreenMode.CONVERSATION:
                self._render_conversation(screen, font_med)
            elif mode == ScreenMode.CAMERA:
                self._render_camera(screen, font_med)
            elif mode == ScreenMode.SPLIT:
                self._render_split(screen, font_small, font_med, font_large, start_time)

            pygame.display.flip()

        pygame.quit()
        log.info("ui_manager.pygame_quit")

    # ── Screen renderers ─────────────────────────────────────────────

    def _render_status(
        self, surface, font_s, font_m, font_l, start_time: float
    ) -> None:
        import pygame

        surface.fill(BG_COLOR)
        x, y = 20, 20

        # Title
        title = font_l.render("JARVIS Status", True, CYAN)
        surface.blit(title, (x, y))
        y += 40

        # Separator
        pygame.draw.line(surface, CYAN, (x, y), (self._width - 20, y), 1)
        y += 15

        # Uptime
        uptime_s = int(time.time() - start_time)
        hours, rem = divmod(uptime_s, 3600)
        mins, secs = divmod(rem, 60)
        lines = [
            (f"Uptime: {hours:02d}:{mins:02d}:{secs:02d}", WHITE),
            (f"Server: {self._server_status}", GREEN if self._server_status == "connected" else RED),
            (f"Screen: {self._screen_mode.name}", CYAN),
            (f"Display: {self._width}x{self._height} @ {self._fps}fps", DIM_WHITE),
            (f"Platform: {platform.machine()}", DIM_WHITE),
        ]

        # System stats — best effort, no crash if unavailable
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0)
            mem = psutil.virtual_memory().percent
            lines.append((f"CPU: {cpu:.0f}%", YELLOW if cpu > 80 else WHITE))
            lines.append((f"Memory: {mem:.0f}%", YELLOW if mem > 80 else WHITE))
        except ImportError:
            lines.append(("CPU/Mem: psutil not available", DIM_WHITE))

        # Temperature (Raspberry Pi)
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                temp_c = int(f.read().strip()) / 1000
            color = RED if temp_c > 75 else (YELLOW if temp_c > 65 else WHITE)
            lines.append((f"Temp: {temp_c:.1f} C", color))
        except (FileNotFoundError, ValueError):
            pass

        for text, color in lines:
            rendered = font_m.render(text, True, color)
            surface.blit(rendered, (x, y))
            y += 28

    def _render_conversation(self, surface, font) -> None:
        surface.fill(BG_COLOR)
        x, y = 15, 15

        role_colors = {
            "user": CYAN,
            "assistant": GREEN,
            "system": ORANGE,
        }

        for role, text in self._conversation:
            color = role_colors.get(role.lower(), WHITE)
            prefix = font.render(f"{role}: ", True, color)
            surface.blit(prefix, (x, y))

            # Wrap text to fit display width
            max_w = self._width - x - prefix.get_width() - 10
            words = text.split()
            line = ""
            tx = x + prefix.get_width()
            for word in words:
                test = f"{line} {word}".strip()
                tw = font.size(test)[0]
                if tw > max_w and line:
                    rendered = font.render(line, True, WHITE)
                    surface.blit(rendered, (tx, y))
                    y += 24
                    tx = x + 20  # indent continuation
                    line = word
                else:
                    line = test
            if line:
                rendered = font.render(line, True, WHITE)
                surface.blit(rendered, (tx, y))
                y += 24

            y += 4  # gap between entries

            if y > self._height - 30:
                break

    def _render_camera(self, surface, font) -> None:
        import pygame

        surface.fill(BG_COLOR)
        if self._camera_surface:
            scaled = pygame.transform.scale(self._camera_surface, (self._width, self._height))
            surface.blit(scaled, (0, 0))
        else:
            msg = font.render("No camera frame", True, DIM_WHITE)
            surface.blit(msg, (self._width // 2 - msg.get_width() // 2, self._height // 2))

    def _render_split(self, surface, font_s, font_m, font_l, start_time: float) -> None:
        import pygame

        surface.fill(BG_COLOR)
        half_w = self._width // 2

        # Left half: face
        face_surf = pygame.Surface((half_w, self._height))
        # Render face scaled to left half
        mini_face = FaceRenderer(half_w, self._height)
        mini_face.set_emotion(self._face.emotion)
        mini_face.set_status(self._face._status_text, self._face._status_color)
        mini_face.update(0)
        mini_face.render(face_surf)
        surface.blit(face_surf, (0, 0))

        # Divider
        pygame.draw.line(surface, CYAN, (half_w, 0), (half_w, self._height), 1)

        # Right half: mini status
        status_surf = pygame.Surface((half_w, self._height))
        status_surf.fill(BG_COLOR)
        self._render_status(status_surf, font_s, font_m, font_l, start_time)
        surface.blit(status_surf, (half_w, 0))
