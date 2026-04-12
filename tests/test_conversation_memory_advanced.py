"""Advanced ConversationMemory tests — edge cases, cleanup, daily summaries."""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parent.parent / "pi"))


@pytest_asyncio.fixture
async def memory():
    from jarvis.memory.conversation_memory import ConversationMemory
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    mem = ConversationMemory()
    mem._db_path = Path(tmp.name)
    await mem.initialize()
    yield mem
    await mem.close()
    os.unlink(tmp.name)


@pytest.mark.asyncio
async def test_multiple_roles(memory):
    await memory.append_exchange("user", "Hello")
    await memory.append_exchange("assistant", "Hi there!")
    await memory.append_exchange("user", "How are you?")
    await memory.append_exchange("assistant", "I'm doing well.")

    ctx = await memory.get_recent_context(10)
    assert "Hello" in ctx
    assert "Hi there!" in ctx
    assert "How are you?" in ctx
    assert "doing well" in ctx


@pytest.mark.asyncio
async def test_context_format_includes_prefixes(memory):
    await memory.append_exchange("user", "Test message")
    await memory.append_exchange("assistant", "Test reply")

    ctx = await memory.get_recent_context(5)
    assert "User:" in ctx
    assert "JARVIS:" in ctx


@pytest.mark.asyncio
async def test_search_by_keyword_multiple_results(memory):
    await memory.append_exchange("user", "I love coffee")
    await memory.append_exchange("user", "Coffee is great")
    await memory.append_exchange("user", "Tea is also nice")

    results = await memory.search_by_keyword("coffee")
    assert len(results) == 2
    for r in results:
        assert "coffee" in r["content"].lower()


@pytest.mark.asyncio
async def test_search_by_keyword_case_insensitive(memory):
    await memory.append_exchange("user", "PYTHON is great")
    results = await memory.search_by_keyword("python")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_search_limit(memory):
    for i in range(10):
        await memory.append_exchange("user", f"keyword message {i}")

    results = await memory.search_by_keyword("keyword", limit=3)
    assert len(results) <= 3


@pytest.mark.asyncio
async def test_save_entity_upsert(memory):
    await memory.save_entity("Vedant", "person", "Owner, likes tea")
    await memory.save_entity("Vedant", "person", "Owner, likes coffee now")

    entity = await memory.get_entity("Vedant")
    assert entity["context"] == "Owner, likes coffee now"


@pytest.mark.asyncio
async def test_multiple_entities(memory):
    await memory.save_entity("Alice", "person", "Developer")
    await memory.save_entity("office", "place", "Main workplace")
    await memory.save_entity("standup", "reminder", "9am daily")

    alice = await memory.get_entity("Alice")
    office = await memory.get_entity("office")
    standup = await memory.get_entity("standup")

    assert alice["type"] == "person"
    assert office["type"] == "place"
    assert standup["type"] == "reminder"


@pytest.mark.asyncio
async def test_get_entity_not_found(memory):
    entity = await memory.get_entity("nonexistent")
    assert entity is None


@pytest.mark.asyncio
async def test_save_daily_summary(memory):
    await memory.save_daily_summary("2024-04-12", "Discussed coffee and tea", ["coffee", "tea"])
    # No assertion error = success; check DB
    cursor = await memory._db.execute("SELECT * FROM summaries WHERE date = '2024-04-12'")
    row = await cursor.fetchone()
    assert row is not None
    assert "coffee" in row[2]  # summary column


@pytest.mark.asyncio
async def test_cleanup_old_removes_aged_records(memory):
    # Insert a very old record directly
    old_ts = time.time() - (40 * 86400)  # 40 days ago
    await memory._db.execute(
        "INSERT INTO exchanges (role, content, timestamp, metadata, session_id) VALUES (?, ?, ?, '{}', '')",
        ("user", "very old message", old_ts),
    )
    await memory._db.commit()

    await memory.cleanup_old()

    cursor = await memory._db.execute(
        "SELECT COUNT(*) FROM exchanges WHERE content = 'very old message'"
    )
    row = await cursor.fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_short_term_trimmed_on_overflow(memory):
    # MEMORY_SHORT_TERM_LIMIT is 5, so 5*2=10 before trim
    for i in range(25):
        await memory.append_exchange("user", f"msg {i}")

    # Short-term should not exceed limit * 2
    from jarvis.config import settings
    assert len(memory._short_term) <= settings.MEMORY_SHORT_TERM_LIMIT * 2


@pytest.mark.asyncio
async def test_context_loads_from_db_when_short_term_empty(memory):
    await memory.append_exchange("user", "stored in db")
    await memory._db.commit()

    # Clear short-term
    memory._short_term.clear()

    ctx = await memory.get_recent_context(5)
    assert "stored in db" in ctx


@pytest.mark.asyncio
async def test_append_with_metadata(memory):
    await memory.append_exchange("user", "test", metadata={"session_id": "abc123"})
    results = await memory.search_by_keyword("test")
    assert len(results) == 1
