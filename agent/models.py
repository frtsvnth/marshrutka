from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class SSEEvent(BaseModel):
    type: str
    data: dict[str, Any] = Field(default_factory=dict)

    def sse_format(self) -> str:
        import json
        body = json.dumps({"type": self.type, **self.data}, ensure_ascii=False)
        return f"event: {self.type}\ndata: {body}\n\n"


MAX_MESSAGE_LENGTH = 8000


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        if len(value) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"Message too long ({len(value)} > {MAX_MESSAGE_LENGTH})")
        return value


class MemoryUpdate(BaseModel):
    key: str
    value: object


class StateSaveRequest(BaseModel):
    session_id: str = ""
    messages: list[dict] = []
    eventTrace: list[dict] = []
    draft: str = ""


class MemoryToolRequest(BaseModel):
    action: str
    key: str = ""
    value: str = ""
    project_id: str = ""
    query: str = ""
    scope: str = "user"


def build_openai_tools() -> list[dict]:
    from agent.tools import TOOL_DEFINITIONS
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in TOOL_DEFINITIONS
    ]


MEMORY_TOOLS = {}


def register_memory_tools(memory_manager):
    MEMORY_TOOLS.clear()
    MEMORY_TOOLS["remember_fact"] = memory_manager.remember_fact
    MEMORY_TOOLS["remember_project_note"] = memory_manager.remember_project_note
    MEMORY_TOOLS["list_memories"] = memory_manager.list_memories
    MEMORY_TOOLS["search_memories"] = memory_manager.search_memories


async def execute_tool(tool_name: str, args: dict[str, Any], memory_manager=None) -> dict[str, Any]:
    if tool_name in MEMORY_TOOLS:
        try:
            result = MEMORY_TOOLS[tool_name](**args)
            if hasattr(result, "__await__"):
                result = await result
            return result if isinstance(result, dict) else {"result": result}
        except Exception as e:
            logger.exception("Memory tool failed: %s(%s)", tool_name, args)
            return {"error": "Ошибка инструмента памяти"}

    from agent.tools import TOOLS
    fn = TOOLS.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        result = fn(**args)
        if hasattr(result, "__await__"):
            result = await result
        return result if isinstance(result, dict) else {"result": result}
    except Exception as e:
        logger.exception("Tool execution failed: %s(%s)", tool_name, args)
        return {"error": "Ошибка инструмента"}
