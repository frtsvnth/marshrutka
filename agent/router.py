from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import DATA_DIR
from agent.memory import AgentMemory
from agent.harness import run_harness
from registry import load_projects

router = APIRouter(prefix="/agent", tags=["agent"])

_memory = AgentMemory(DATA_DIR / "agent_memory.json")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""
    history: list[ChatMessage] = []


@router.post("/chat")
async def chat(req: ChatRequest):
    history = [{"role": m.role, "content": m.content} for m in req.history]

    async def event_stream():
        try:
            async for chunk in run_harness(req.message, history, _memory):
                if isinstance(chunk, str) and chunk.startswith("{"):
                    try:
                        parsed = json.loads(chunk)
                        if "tool_indicator" in parsed:
                            yield f"data: {json.dumps({'tool_indicator': parsed['tool_indicator']})}\n\n"
                            continue
                    except json.JSONDecodeError:
                        pass
                yield f"data: {json.dumps({'content': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/context")
async def get_context():
    projects = load_projects()
    return {
        "user_context": _memory.data.get("user_context", {}),
        "history_count": len(_memory.data.get("conversation_history", [])),
        "project_count": len(projects),
        "projects": [
            {
                "project_id": p.project_id,
                "display_name": p.display_name,
                "enabled": p.enabled,
            }
            for p in projects
        ],
    }


class MemoryUpdate(BaseModel):
    key: str
    value: object


@router.post("/memory")
async def update_memory(body: MemoryUpdate):
    _memory.update_user_context(body.key, body.value)
    return {"ok": True}


@router.delete("/history")
async def clear_history():
    _memory.data["conversation_history"] = []
    _memory.save()
    return {"ok": True}
