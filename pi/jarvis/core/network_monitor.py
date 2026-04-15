"""
Network Monitor — tracks internet/WiFi connectivity and selects the AI mode.

Three modes:
  FULL_CLOUD   — internet reachable  → Gemini Live (primary)
  LOCAL_SERVER — network but no WAN  → Ollama via server or Pi-local Ollama
  OFFLINE      — no network at all   → local Ollama + Piper TTS only

Mode is re-evaluated every NETWORK_CHECK_INTERVAL seconds.
Hysteresis: requires NETWORK_FAIL_THRESHOLD consecutive failures before
downgrading from FULL_CLOUD, preventing thrashing on flaky connections.
Upgrade to FULL_CLOUD happens immediately on first successful ping.
"""

import asyncio
import logging
from enum import Enum, auto

from jarvis.config import settings
from jarvis.core.event_bus import event_bus

logger = logging.getLogger(__name__)


class NetworkMode(Enum):
    FULL_CLOUD = auto()    # WiFi + internet → Gemini Live
    LOCAL_SERVER = auto()  # WiFi / LAN only → Ollama server or local
    OFFLINE = auto()       # No network      → local Ollama + TTS only


class NetworkMonitor:
    """Monitors internet connectivity and publishes mode-change events."""

    def __init__(self) -> None:
        self._mode = NetworkMode.OFFLINE  # conservative default until first check
        self._task: asyncio.Task | None = None
        self._fail_count = 0  # consecutive internet check failures

    @property
    def mode(self) -> NetworkMode:
        return self._mode

    @property
    def internet_available(self) -> bool:
        return self._mode == NetworkMode.FULL_CLOUD

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        """Run initial check synchronously so mode is known before first trigger."""
        await self._update_mode()
        logger.info(
            "Network monitor started — mode=%s (ping_host=%s)",
            self._mode.name,
            settings.NETWORK_PING_HOST,
        )
        self._task = asyncio.create_task(self._monitor_loop(), name="network_monitor")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Network monitor stopped")

    # ── Internal loop ────────────────────────────────────────────────

    async def _monitor_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(settings.NETWORK_CHECK_INTERVAL)
                await self._update_mode()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Network monitor error")

    async def _update_mode(self) -> None:
        """Re-evaluate mode and publish event if it changed."""
        old_mode = self._mode
        new_mode = await self._detect_mode()

        if new_mode == old_mode:
            return

        # Hysteresis: don't drop from FULL_CLOUD until N consecutive failures
        if old_mode == NetworkMode.FULL_CLOUD and new_mode != NetworkMode.FULL_CLOUD:
            self._fail_count += 1
            if self._fail_count < settings.NETWORK_FAIL_THRESHOLD:
                logger.debug(
                    "Internet check failed (%d/%d) — staying FULL_CLOUD",
                    self._fail_count,
                    settings.NETWORK_FAIL_THRESHOLD,
                )
                return
        else:
            self._fail_count = 0

        self._mode = new_mode
        logger.info("Network mode: %s → %s", old_mode.name, new_mode.name)
        await event_bus.publish("network.mode_changed", {
            "mode": new_mode.name,
            "previous": old_mode.name,
            "internet": new_mode == NetworkMode.FULL_CLOUD,
        })

        # Convenience events
        if new_mode == NetworkMode.FULL_CLOUD:
            await event_bus.publish("network.internet_up", {})
        elif old_mode == NetworkMode.FULL_CLOUD:
            await event_bus.publish("network.internet_down", {})

    async def _detect_mode(self) -> NetworkMode:
        """
        Mode resolution:
        1. Ping NETWORK_PING_HOST (8.8.8.8) — internet reachable → FULL_CLOUD
        2. Ping local gateway (ip route get) — LAN alive → LOCAL_SERVER
        3. Nothing reachable → OFFLINE
        """
        if await self._ping(settings.NETWORK_PING_HOST, timeout=3):
            return NetworkMode.FULL_CLOUD

        if await self._has_local_network():
            return NetworkMode.LOCAL_SERVER

        return NetworkMode.OFFLINE

    @staticmethod
    async def _ping(host: str, timeout: int = 3) -> bool:
        """Return True if host responds to a single ICMP ping within timeout."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", "1", "-W", str(timeout), host,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=timeout + 1)
            return proc.returncode == 0
        except (asyncio.TimeoutError, Exception):
            return False

    @staticmethod
    async def _has_local_network() -> bool:
        """Check if a default route exists (i.e. interface is up even without internet)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ip", "route", "show", "default",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
            return bool(stdout.strip())  # non-empty = at least one default route
        except Exception:
            return False


# Singleton
network_monitor = NetworkMonitor()
