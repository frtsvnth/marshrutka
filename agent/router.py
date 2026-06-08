from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, JSONResponse

from agent.memory import MemoryManager
from agent.harness import run_harness
from agent.models import (
    ChatRequest,
    MemoryUpdate,
    SSEEvent,
    StateSaveRequest,
    MemoryToolRequest,
    register_memory_tools,
)
from agent.session import validate_session_id
from agent.voice import transcribe_audio
from registry import load_projects
from config import DATA_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])

_memory_manager = MemoryManager()
register_memory_tools(_memory_manager)

AGENT_STATE_DIR = DATA_DIR / "agent" / "states"
AGENT_STATE_DIR.mkdir(parents=True, exist_ok=True)


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
            "user_facts": _memory_manager.user_facts.data,
            "project_memories": _memory_manager.project_memory.data,
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
        "user_facts": _memory_manager.user_facts.data,
        "project_memories": _memory_manager.project_memory.data,
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


@router.post("/memory-tool")
async def memory_tool(body: MemoryToolRequest):
    if body.action == "remember_fact":
        return _memory_manager.remember_fact(body.key, body.value)
    elif body.action == "remember_project_note":
        return _memory_manager.remember_project_note(body.project_id, body.key, body.value)
    elif body.action == "list_memories":
        return _memory_manager.list_memories(body.scope)
    elif body.action == "search_memories":
        return _memory_manager.search_memories(body.query)
    raise HTTPException(status_code=422, detail="Unknown action")


@router.delete("/history")
async def clear_history(session_id: str = ""):
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")

    sid = _resolve_session(session_id)
    _, session_memory = _memory_manager.get_session(sid)
    session_memory.clear()
    _memory_manager.drop_session(sid)
    return {"ok": True}


@router.post("/state/save")
async def save_state(body: StateSaveRequest):
    sid = body.session_id or "anonymous"
    safe_sid = "".join(c for c in sid if c.isalnum() or c in "-_")[:64]
    state_file = AGENT_STATE_DIR / f"{safe_sid}.json"
    try:
        state_file.write_text(
            json.dumps({
                "session_id": sid,
                "messages": body.messages,
                "eventTrace": body.eventTrace,
                "draft": body.draft,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        return {"ok": True}
    except Exception as e:
        logger.exception("Failed to save state")
        return {"ok": False, "error": str(e)}


@router.get("/state/load")
async def load_state(session_id: str = ""):
    sid = session_id or "anonymous"
    safe_sid = "".join(c for c in sid if c.isalnum() or c in "-_")[:64]
    state_file = AGENT_STATE_DIR / f"{safe_sid}.json"
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            return data
        except Exception:
            return {"session_id": sid, "messages": [], "eventTrace": [], "draft": ""}
    return {"session_id": sid, "messages": [], "eventTrace": [], "draft": ""}


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    audio_data = await file.read()
    result = await transcribe_audio(audio_data, file.filename or "recording.webm")
    return result
