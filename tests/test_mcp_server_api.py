"""
Live HTTP tests for the MCP Tool Server (FastAPI on port 8088).

Tests all REST endpoints: GET /tools, POST /tools/{name}, GET /health.
The server is started in a background thread for the duration of the session.
"""

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "pi"))

# ── In-process TestClient approach (no real server needed) ────────────

@pytest.fixture(scope="module")
def client():
    """Return a Starlette TestClient for the MCP FastAPI app."""
    from starlette.testclient import TestClient
    from jarvis.tools.mcp_server import app, _tool_registry
    _tool_registry.clear()
    with TestClient(app) as c:
        yield c
    _tool_registry.clear()


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "tools" in data


def test_list_tools_empty(client):
    from jarvis.tools.mcp_server import _tool_registry
    _tool_registry.clear()
    resp = client.get("/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert "tools" in data
    assert isinstance(data["tools"], list)


def test_register_and_list_tool(client):
    from jarvis.tools.mcp_server import mcp_tool, _tool_registry
    _tool_registry.clear()

    @mcp_tool(name="ping", description="Return pong")
    async def ping():
        return {"pong": True}

    resp = client.get("/tools")
    tools = resp.json()["tools"]
    names = [t["name"] for t in tools]
    assert "ping" in names


def test_execute_tool_via_post(client):
    from jarvis.tools.mcp_server import mcp_tool, _tool_registry
    _tool_registry.clear()

    @mcp_tool(
        name="double",
        description="Double a number",
        parameters={
            "type": "object",
            "properties": {"n": {"type": "integer"}},
            "required": ["n"],
        },
    )
    async def double(n: int):
        return {"result": n * 2}

    resp = client.post("/tools/double", json={"n": 6})
    assert resp.status_code == 200
    assert resp.json()["result"]["result"] == 12


def test_execute_unknown_tool_via_post(client):
    from jarvis.tools.mcp_server import _tool_registry
    _tool_registry.clear()
    resp = client.post("/tools/nonexistent", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data


def test_health_reflects_tool_count(client):
    from jarvis.tools.mcp_server import mcp_tool, _tool_registry
    _tool_registry.clear()

    @mcp_tool(name="t1", description="Tool 1")
    async def t1(): return {}

    @mcp_tool(name="t2", description="Tool 2")
    async def t2(): return {}

    resp = client.get("/health")
    assert resp.json()["tools"] == 2


def test_tool_with_no_parameters(client):
    from jarvis.tools.mcp_server import mcp_tool, _tool_registry
    _tool_registry.clear()

    @mcp_tool(name="noop", description="Do nothing")
    async def noop():
        return {"ok": True}

    resp = client.post("/tools/noop", json={})
    assert resp.status_code == 200
    assert resp.json()["result"]["ok"] is True


def test_tool_schema_structure(client):
    from jarvis.tools.mcp_server import mcp_tool, _tool_registry
    _tool_registry.clear()

    @mcp_tool(
        name="greet",
        description="Say hello",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    )
    async def greet(name: str):
        return {"message": f"Hello, {name}!"}

    resp = client.get("/tools")
    tool = next(t for t in resp.json()["tools"] if t["name"] == "greet")
    assert tool["description"] == "Say hello"
    assert "parameters" in tool
    assert "name" in tool["parameters"]["properties"]
