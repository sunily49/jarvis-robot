"""Tests for Memory MCP Tools — recall, save_note, recall_entity, get_recent_context."""

import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parent.parent / "pi"))


@pytest_asyncio.fixture
async def memory():
    """Fresh ConversationMemory backed by a temp DB."""
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
async def test_recall_conversation_empty(memory, monkeypatch):
    import jarvis.memory.conversation_memory as cm_module
    monkeypatch.setattr(cm_module, "conversation_memory", memory)

    from jarvis.tools.mcp_server import _tool_registry
    _tool_registry.clear()
    import jarvis.tools.memory_tools  # noqa — registers tools

    from jarvis.tools.mcp_server import execute_tool
    result = await execute_tool("recall_conversation", {"keyword": "anything"})
    assert "results" in result
    assert result["results"] == []


@pytest.mark.asyncio
async def test_save_note_and_recall(memory, monkeypatch):
    import jarvis.memory.conversation_memory as cm_module
    monkeypatch.setattr(cm_module, "conversation_memory", memory)

    from jarvis.tools.mcp_server import _tool_registry
    _tool_registry.clear()
    import importlib
    import jarvis.tools.memory_tools
    importlib.reload(jarvis.tools.memory_tools)

    from jarvis.tools.mcp_server import execute_tool

    # Save a note
    result = await execute_tool("save_note", {
        "name": "meeting",
        "content": "Team meeting at 3pm Friday",
        "type": "reminder",
    })
    assert result["status"] == "saved"
    assert result["name"] == "meeting"

    # Recall it
    result2 = await execute_tool("recall_entity", {"name": "meeting"})
    assert result2["name"] == "meeting"
    assert "3pm" in result2["context"]


@pytest.mark.asyncio
async def test_recall_entity_missing(memory, monkeypatch):
    import jarvis.memory.conversation_memory as cm_module
    monkeypatch.setattr(cm_module, "conversation_memory", memory)

    from jarvis.tools.mcp_server import _tool_registry
    _tool_registry.clear()
    import importlib
    import jarvis.tools.memory_tools
    importlib.reload(jarvis.tools.memory_tools)

    from jarvis.tools.mcp_server import execute_tool
    result = await execute_tool("recall_entity", {"name": "nonexistent"})
    assert "error" in result


@pytest.mark.asyncio
async def test_get_recent_context_empty(memory, monkeypatch):
    import jarvis.memory.conversation_memory as cm_module
    monkeypatch.setattr(cm_module, "conversation_memory", memory)

    from jarvis.tools.mcp_server import _tool_registry
    _tool_registry.clear()
    import importlib
    import jarvis.tools.memory_tools
    importlib.reload(jarvis.tools.memory_tools)

    from jarvis.tools.mcp_server import execute_tool
    result = await execute_tool("get_recent_context", {"count": 5})
    assert "context" in result
    assert result["context"] == ""


@pytest.mark.asyncio
async def test_get_recent_context_with_exchanges(memory, monkeypatch):
    import jarvis.memory.conversation_memory as cm_module
    monkeypatch.setattr(cm_module, "conversation_memory", memory)

    from jarvis.tools.mcp_server import _tool_registry
    _tool_registry.clear()
    import importlib
    import jarvis.tools.memory_tools
    importlib.reload(jarvis.tools.memory_tools)

    from jarvis.tools.mcp_server import execute_tool

    await memory.append_exchange("user", "What is 2+2?")
    await memory.append_exchange("assistant", "2+2 equals 4.")

    result = await execute_tool("get_recent_context", {"count": 5})
    assert "2+2" in result["context"]
    assert "4" in result["context"]


@pytest.mark.asyncio
async def test_recall_by_keyword(memory, monkeypatch):
    import jarvis.memory.conversation_memory as cm_module
    monkeypatch.setattr(cm_module, "conversation_memory", memory)

    from jarvis.tools.mcp_server import _tool_registry
    _tool_registry.clear()
    import importlib
    import jarvis.tools.memory_tools
    importlib.reload(jarvis.tools.memory_tools)

    from jarvis.tools.mcp_server import execute_tool

    await memory.append_exchange("user", "Remind me about the dentist")
    await memory.append_exchange("user", "What's the weather?")

    result = await execute_tool("recall_conversation", {"keyword": "dentist", "limit": 5})
    assert len(result["results"]) == 1
    assert "dentist" in result["results"][0]["content"]
