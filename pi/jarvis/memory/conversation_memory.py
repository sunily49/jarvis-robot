"""
Conversation Memory — short/medium/long-term memory in SQLite.

Layers:
- Short-term: last N exchanges in current session (in-memory)
- Medium-term: all exchanges from today (SQLite)
- Long-term: summaries + entity extraction (SQLite, future: vector DB)

All data stays local on Pi. Never sent to cloud.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite

from jarvis.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Exchange:
    role: str           # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class ConversationMemory:
    """Multi-layer conversation memory backed by SQLite."""

    def __init__(self) -> None:
        self._db_path = Path(settings.MEMORY_DB_PATH)
        self._short_term: list[Exchange] = []
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create database and tables."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS exchanges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL NOT NULL,
                metadata TEXT DEFAULT '{}',
                session_id TEXT
            );
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                context TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                summary TEXT NOT NULL,
                entity_mentions TEXT DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_exchanges_ts ON exchanges(timestamp);
            CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
        """)
        await self._db.commit()
        logger.info("Conversation memory initialized at %s", self._db_path)

    async def append_exchange(
        self,
        role: str,
        content: str,
        metadata: dict | None = None,
        session_id: str = "",
    ) -> None:
        """Record an exchange (user utterance or assistant response)."""
        exchange = Exchange(role=role, content=content, metadata=metadata or {})
        self._short_term.append(exchange)

        # Trim short-term to limit
        if len(self._short_term) > settings.MEMORY_SHORT_TERM_LIMIT * 2:
            self._short_term = self._short_term[-settings.MEMORY_SHORT_TERM_LIMIT * 2:]

        # Persist to SQLite
        if self._db:
            await self._db.execute(
                "INSERT INTO exchanges (role, content, timestamp, metadata, session_id) VALUES (?, ?, ?, ?, ?)",
                (role, content, exchange.timestamp, json.dumps(metadata or {}), session_id),
            )
            await self._db.commit()

    async def get_recent_context(self, n: int = 0) -> str:
        """Get recent conversation context as formatted string for system prompt."""
        n = n or settings.MEMORY_SHORT_TERM_LIMIT
        exchanges = self._short_term[-n * 2:] if self._short_term else []

        if not exchanges and self._db:
            # Load from DB if short-term is empty (new session)
            cursor = await self._db.execute(
                "SELECT role, content, timestamp FROM exchanges ORDER BY timestamp DESC LIMIT ?",
                (n * 2,),
            )
            rows = await cursor.fetchall()
            for row in reversed(rows):
                exchanges.append(Exchange(role=row[0], content=row[1], timestamp=row[2]))

        if not exchanges:
            return ""

        lines = []
        for ex in exchanges:
            prefix = "User" if ex.role == "user" else "JARVIS"
            lines.append(f"{prefix}: {ex.content}")
        return "\n".join(lines)

    async def search_by_keyword(self, keyword: str, limit: int = 10) -> list[dict]:
        """Search past conversations by keyword."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT role, content, timestamp FROM exchanges WHERE content LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{keyword}%", limit),
        )
        rows = await cursor.fetchall()
        return [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in rows]

    async def save_entity(self, name: str, entity_type: str, context: str = "") -> None:
        """Save or update a named entity (person, place, preference)."""
        if not self._db:
            return
        now = time.time()
        await self._db.execute(
            """INSERT INTO entities (name, type, first_seen, last_seen, context)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET last_seen=?, context=?""",
            (name, entity_type, now, now, context, now, context),
        )
        await self._db.commit()

    async def get_entity(self, name: str) -> dict | None:
        """Retrieve entity info."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT name, type, first_seen, last_seen, context FROM entities WHERE name = ?",
            (name,),
        )
        row = await cursor.fetchone()
        if row:
            return {
                "name": row[0], "type": row[1],
                "first_seen": row[2], "last_seen": row[3], "context": row[4],
            }
        return None

    async def save_daily_summary(self, date: str, summary: str, entities: list[str] | None = None) -> None:
        """Save a daily conversation summary."""
        if not self._db:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO summaries (date, summary, entity_mentions) VALUES (?, ?, ?)",
            (date, summary, json.dumps(entities or [])),
        )
        await self._db.commit()

    async def cleanup_old(self) -> None:
        """Remove exchanges older than retention period."""
        if not self._db:
            return
        cutoff = time.time() - (settings.MEMORY_RETENTION_DAYS * 86400)
        await self._db.execute("DELETE FROM exchanges WHERE timestamp < ?", (cutoff,))
        await self._db.commit()
        logger.info("Cleaned up exchanges older than %d days", settings.MEMORY_RETENTION_DAYS)

    async def close(self) -> None:
        if self._db:
            await self._db.close()


# Singleton
conversation_memory = ConversationMemory()
