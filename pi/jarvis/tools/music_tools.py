"""
Music MCP Tools — YouTube Music search + yt-dlp + mpv playback.
"""

import asyncio
import logging
import subprocess
from typing import Any

from jarvis.tools.mcp_server import mcp_tool

logger = logging.getLogger(__name__)

# Track current mpv process
_mpv_process: subprocess.Popen | None = None


@mcp_tool(
    name="play_song",
    description="Search for and play a song from YouTube Music.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Song name and/or artist"},
        },
        "required": ["query"],
    },
)
async def play_song(query: str) -> dict[str, Any]:
    global _mpv_process
    loop = asyncio.get_event_loop()

    try:
        # Search YouTube Music
        from ytmusicapi import YTMusic
        yt = YTMusic()
        results = await loop.run_in_executor(
            None, lambda: yt.search(query, filter="songs", limit=1)
        )
        if not results:
            return {"error": "No results found"}

        song = results[0]
        video_id = song.get("videoId")
        title = song.get("title", "Unknown")
        artist = song.get("artists", [{}])[0].get("name", "Unknown")

        # Stop current playback
        await stop_playback()

        # Play via yt-dlp piped to mpv
        url = f"https://music.youtube.com/watch?v={video_id}"
        _mpv_process = subprocess.Popen(
            ["mpv", "--no-video", "--really-quiet", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        logger.info("Playing: %s - %s", artist, title)
        return {"status": "playing", "title": title, "artist": artist}
    except Exception as e:
        return {"error": str(e)}


@mcp_tool(
    name="stop_playback",
    description="Stop the currently playing music.",
    parameters={"type": "object", "properties": {}},
)
async def stop_playback() -> dict[str, Any]:
    global _mpv_process
    if _mpv_process and _mpv_process.poll() is None:
        _mpv_process.terminate()
        _mpv_process = None
        return {"status": "stopped"}
    return {"status": "nothing_playing"}


@mcp_tool(
    name="set_volume",
    description="Set the system audio volume (0-100).",
    parameters={
        "type": "object",
        "properties": {
            "level": {"type": "integer", "description": "Volume level 0-100"},
        },
        "required": ["level"],
    },
)
async def set_volume(level: int) -> dict[str, Any]:
    level = max(0, min(100, level))
    try:
        subprocess.run(
            ["amixer", "set", "Master", f"{level}%"],
            capture_output=True,
            timeout=5,
        )
        return {"status": "ok", "volume": level}
    except Exception as e:
        return {"error": str(e)}
