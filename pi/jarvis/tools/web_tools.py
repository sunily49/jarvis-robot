"""
Web Search MCP Tools — DuckDuckGo search and Wikipedia.
"""

from typing import Any

from jarvis.tools.mcp_server import mcp_tool


@mcp_tool(
    name="web_search",
    description="Search the web using DuckDuckGo. Returns top results with titles and snippets.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    },
)
async def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    import asyncio
    try:
        from duckduckgo_search import DDGS
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None,
            lambda: list(DDGS().text(query, max_results=max_results)),
        )
        return {
            "results": [
                {"title": r.get("title", ""), "snippet": r.get("body", ""), "url": r.get("href", "")}
                for r in results
            ]
        }
    except Exception as e:
        return {"error": str(e)}


@mcp_tool(
    name="wikipedia_summary",
    description="Get a Wikipedia summary for a topic.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Wikipedia article title or search term"},
        },
        "required": ["topic"],
    },
)
async def wikipedia_summary(topic: str) -> dict[str, Any]:
    import asyncio
    import json
    try:
        import aiohttp
        url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + topic.replace(" ", "_")
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "title": data.get("title", ""),
                        "summary": data.get("extract", ""),
                        "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                    }
                return {"error": f"Wikipedia returned status {resp.status}"}
    except Exception as e:
        return {"error": str(e)}
