"""Tests for MCP tool registry and execution."""

import pytest

from jarvis.tools.mcp_server import mcp_tool, get_tool_schemas, execute_tool, _tool_registry


@pytest.fixture(autouse=True)
def clean_registry():
    _tool_registry.clear()
    yield
    _tool_registry.clear()


def test_register_tool():
    @mcp_tool(name="test_tool", description="A test tool")
    async def my_tool():
        return {"ok": True}

    schemas = get_tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "test_tool"


@pytest.mark.asyncio
async def test_execute_tool():
    @mcp_tool(
        name="add",
        description="Add two numbers",
        parameters={"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
    )
    async def add(a: int, b: int):
        return {"sum": a + b}

    result = await execute_tool("add", {"a": 3, "b": 4})
    assert result["sum"] == 7


@pytest.mark.asyncio
async def test_execute_unknown_tool():
    with pytest.raises(ValueError, match="Unknown tool"):
        await execute_tool("nonexistent", {})
