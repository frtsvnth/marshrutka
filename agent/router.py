from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from agent.memory import MemoryManager
from agent.harness import run_harness
from agent.models import (
    ChatRequest,
    MemoryUpdate,
    SSEEvent,
)
from agent.session import validate_session_id
from registry import load_projects

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])

_memory_manager = MemoryManager()


def _resolve_session(session_id: str) -> str:
    try:
        return validate_session_id(session_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/chat")
async def chat(req: ChatRequest):
    if req.session_id:
        session_id = _resolve_session(req.session_id)
    else:
        session_id = ""

    resolved_id, _ = _memory_manager.get_session(session_id)

    async def event_stream():
        try:
            yield SSEEvent(type="session", data={"session_id": resolved_id}).sse_format()

            async for event in run_harness(req.message, _memory_manager, resolved_id):
                yield event.sse_format()

            yield SSEEvent(type="done").sse_format()

        except Exception as e:
            logger.exception("Chat error for session %s", resolved_id)
            yield SSEEvent(type="error", data={
                "message": "Внутренняя ошибка. Попробуйте ещё раз."
            }).sse_format()
            yield SSEEvent(type="done").sse_format()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/context")
async def get_context(session_id: str = ""):
    if not session_id:
        projects = load_projects()
        return {
            "session_id": None,
            "user_context": _memory_manager.profile.data,
            "history_count": 0,
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

    sid = _resolve_session(session_id)
    _, session_memory = _memory_manager.get_session(sid)

    projects = load_projects()
    return {
        "session_id": sid,
        "user_context": _memory_manager.profile.data,
        "history_count": len(session_memory.data.get("messages", [])),
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


@router.post("/memory")
async def update_memory(body: MemoryUpdate):
    _memory_manager.profile.update(body.key, body.value)
    return {"ok": True}


@router.delete("/history")
async def clear_history(session_id: str = ""):
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")

    sid = _resolve_session(session_id)
    _, session_memory = _memory_manager.get_session(sid)
    session_memory.clear()
    _memory_manager.drop_session(sid)
    return {"ok": True}
