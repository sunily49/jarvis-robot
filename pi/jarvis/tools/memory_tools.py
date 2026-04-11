"""
Memory MCP Tools — conversation memory access for Gemini.
"""

from typing import Any

from jarvis.tools.mcp_server import mcp_tool


@mcp_tool(
    name="recall_conversation",
    description="Search past conversations by keyword. Returns matching exchanges.",
    parameters={
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "Search keyword"},
            "limit": {"type": "integer", "default": 5},
        },
        "required": ["keyword"],
    },
)
async def recall_conversation(keyword: str, limit: int = 5) -> dict[str, Any]:
    from jarvis.memory.conversation_memory import conversation_memory
    results = await conversation_memory.search_by_keyword(keyword, limit)
    return {"results": results}


@mcp_tool(
    name="save_note",
    description="Save a note or piece of information to long-term memory.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name/label for the note"},
            "content": {"type": "string", "description": "Content to remember"},
            "type": {"type": "string", "description": "Category: person, preference, fact, reminder", "default": "fact"},
        },
        "required": ["name", "content"],
    },
)
async def save_note(name: str, content: str, type: str = "fact") -> dict[str, Any]:
    from jarvis.memory.conversation_memory import conversation_memory
    await conversation_memory.save_entity(name, type, content)
    return {"status": "saved", "name": name}


@mcp_tool(
    name="recall_entity",
    description="Recall a saved entity (person, preference, fact) by name.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the entity to recall"},
        },
        "required": ["name"],
    },
)
async def recall_entity(name: str) -> dict[str, Any]:
    from jarvis.memory.conversation_memory import conversation_memory
    entity = await conversation_memory.get_entity(name)
    if entity:
        return entity
    return {"error": f"No entity found with name '{name}'"}


@mcp_tool(
    name="get_recent_context",
    description="Get the most recent conversation exchanges for context.",
    parameters={
        "type": "object",
        "properties": {
            "count": {"type": "integer", "description": "Number of exchanges to retrieve", "default": 5},
        },
    },
)
async def get_recent_context(count: int = 5) -> dict[str, Any]:
    from jarvis.memory.conversation_memory import conversation_memory
    context = await conversation_memory.get_recent_context(count)
    return {"context": context}
