"""
MCP Tool Server — FastAPI on localhost:8080.

Registers all enabled tools and provides:
1. Gemini function-calling schema generation
2. Tool execution dispatcher
3. REST API for external access
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine

from fastapi import FastAPI
from jarvis.config import settings

logger = logging.getLogger(__name__)

app = FastAPI(title="JARVIS MCP Tools", version="1.0.0")

# ── Tool Registry ─────────────────────────────────────────────────────

ToolFunction = Callable[..., Coroutine[Any, Any, Any]]

_tool_registry: dict[str, dict[str, Any]] = {}
# name → {"function": callable, "schema": gemini_schema_dict}


def mcp_tool(
    name: str,
    description: str,
    parameters: dict[str, Any] | None = None,
):
    """Decorator to register a function as an MCP tool for Gemini function calling."""

    def decorator(fn: ToolFunction) -> ToolFunction:
        schema = {
            "name": name,
            "description": description,
        }
        if parameters:
            schema["parameters"] = parameters

        _tool_registry[name] = {
            "function": fn,
            "schema": schema,
        }
        logger.debug("MCP tool registered: %s", name)
        return fn

    return decorator


def get_tool_schemas() -> list[dict[str, Any]]:
    """Get all registered tool schemas for Gemini function-calling setup."""
    return [entry["schema"] for entry in _tool_registry.values()]


def get_tool_schemas_dict() -> dict[str, dict[str, Any]]:
    """Get schemas as a dict keyed by tool name (for GeminiLiveClient)."""
    return {name: entry["schema"] for name, entry in _tool_registry.items()}


async def execute_tool(name: str, args: dict[str, Any]) -> Any:
    """Execute a registered tool by name with given arguments."""
    entry = _tool_registry.get(name)
    if not entry:
        raise ValueError(f"Unknown tool: {name}")

    fn = entry["function"]
    logger.info("Executing tool: %s(%s)", name, args)

    try:
        result = await fn(**args)
        return result
    except TypeError as e:
        logger.error("Tool %s argument error: %s", name, e)
        raise


# ── REST API endpoints ────────────────────────────────────────────────

@app.get("/tools")
async def list_tools():
    """List all registered tools."""
    return {"tools": get_tool_schemas()}


@app.post("/tools/{tool_name}")
async def call_tool(tool_name: str, args: dict[str, Any] = {}):
    """Execute a tool via REST API."""
    try:
        result = await execute_tool(tool_name, args)
        return {"result": result}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


@app.get("/health")
async def health():
    return {"status": "ok", "tools": len(_tool_registry)}


# ── Server runner ─────────────────────────────────────────────────────

async def start_mcp_server() -> None:
    """Start the MCP tool server as a background asyncio task."""
    import uvicorn

    config = uvicorn.Config(
        app,
        host=settings.MCP_HOST,
        port=settings.MCP_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    logger.info("MCP tool server starting on %s:%d", settings.MCP_HOST, settings.MCP_PORT)
    await server.serve()
