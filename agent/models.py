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


async def execute_tool(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
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
