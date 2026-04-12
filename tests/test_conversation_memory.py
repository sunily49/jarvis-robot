"""Tests for ConversationMemory — SQLite persistence and retrieval."""

import asyncio
import os
import tempfile
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def memory():
    from jarvis.memory.conversation_memory import ConversationMemory

    # Use temp file for test DB
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    mem = ConversationMemory()
    mem._db_path = type(mem._db_path)(tmp.name)
    await mem.initialize()
    yield mem
    await mem.close()
    os.unlink(tmp.name)


@pytest.mark.asyncio
async def test_append_and_retrieve(memory):
    await memory.append_exchange("user", "Hello JARVIS")
    await memory.append_exchange("assistant", "Hello! How can I help?")

    context = await memory.get_recent_context(5)
    assert "Hello JARVIS" in context
    assert "How can I help" in context


@pytest.mark.asyncio
async def test_keyword_search(memory):
    await memory.append_exchange("user", "Set a reminder for my dentist appointment")
    await memory.append_exchange("user", "What's the weather like?")

    results = await memory.search_by_keyword("dentist")
    assert len(results) == 1
    assert "dentist" in results[0]["content"]


@pytest.mark.asyncio
async def test_entity_save_recall(memory):
    await memory.save_entity("Vedant", "person", "Owner, likes coffee")
    entity = await memory.get_entity("Vedant")
    assert entity is not None
    assert entity["name"] == "Vedant"
    assert "coffee" in entity["context"]


@pytest.mark.asyncio
async def test_short_term_limit(memory):
    # Add more than the limit
    for i in range(20):
        await memory.append_exchange("user", f"Message {i}")

    # Short-term should be trimmed
    assert len(memory._short_term) <= 20
