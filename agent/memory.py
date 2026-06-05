from __future__ import annotations

import json
import logging
import tempfile
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR
from agent.session import validate_session_id

logger = logging.getLogger(__name__)

AGENT_DIR = DATA_DIR / "agent"
SESSIONS_DIR = AGENT_DIR / "sessions"
USER_PROFILE_FILE = AGENT_DIR / "user_profile.json"
PROJECT_NOTES_FILE = AGENT_DIR / "project_notes.json"

AGENT_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

MAX_HISTORY = 20
RECENT_WINDOW = 10
MAX_CACHED_SESSIONS = 100

BASE_SYSTEM_PROMPT = """
Ты — Маршал, AI-ассистент инструмента Marshrutka для запуска контентных пайплайнов.

Твои возможности:
- Отвечать на вопросы про контент (написать текст, придумать тему, проверить длину)
- Работать с проектами: смотреть список, последние запуски, статусы
- Запускать пайплайны проектов через инструменты
- Создавать расписания для проектов
- Проверять результаты своей работы через инструменты (харнесс-цикл)
- Искать информацию в интернете через search_web
- Искать видео на YouTube через search_youtube

ВАЖНО:
- Когда нужно выполнить действие — используй инструменты.
- После генерации текста вызови count_words, убедись в правильности длины.
- Если длина не совпадает — скорректируй текст и проверь снова.
- Не выдумывай информацию о проектах — используй get_projects для получения актуальных данных.
- Не говори "у меня нет доступа в интернет" — у тебя есть search_web и search_youtube.
- Если пользователь просит найти ссылки, статьи, новости, референсы — используй search_web.
- Если просит найти YouTube видео — используй search_youtube.
- Не выдумывай ссылки. Используй только реальные результаты из инструментов.
"""


def _atomic_save(filepath: Path, data: Any):
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=str(filepath.parent),
        prefix=f".{filepath.stem}_tmp_",
        suffix=".json",
        delete=False,
        encoding="utf-8",
    )
    try:
        json.dump(data, tmp, indent=2, ensure_ascii=False, default=str)
        tmp.close()
        Path(tmp.name).replace(filepath)
    except Exception:
        Path(tmp.name).unlink(missing_ok=True)
        raise


def _read_json(filepath: Path, default: Any = None) -> Any:
    if filepath.exists():
        try:
            return json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read %s: %s", filepath, e)
    return default if default is not None else {}


class ProfileMemory:
    def __init__(self, filepath: Path = USER_PROFILE_FILE):
        self.filepath = filepath
        self.data = _read_json(filepath, {"name": "", "preferences": [], "notes": []})

    def save(self):
        _atomic_save(self.filepath, self.data)

    def get_context_text(self) -> str:
        parts = []
        if self.data.get("name"):
            parts.append(f"Имя пользователя: {self.data['name']}")
        if self.data.get("preferences"):
            parts.append(f"Предпочтения: {', '.join(self.data['preferences'])}")
        if self.data.get("notes"):
            parts.append(f"Заметки: {'; '.join(self.data['notes'])}")
        if parts:
            return "Известная информация о пользователе:\n" + "\n".join(parts)
        return ""

    def update(self, key: str, value: Any):
        self.data[key] = value
        self.save()


class SessionMemory:
    def __init__(self, session_id: str):
        validate_session_id(session_id)
        self.session_id = session_id
        self.filepath = SESSIONS_DIR / f"{session_id}.json"
        self.data = _read_json(self.filepath, {"messages": [], "created_at": _now_iso()})

    def save(self):
        _atomic_save(self.filepath, self.data)

    def add_message(self, role: str, content: str):
        messages = self.data.setdefault("messages", [])
        messages.append({"role": role, "content": content, "timestamp": _now_iso()})
        if len(messages) > MAX_HISTORY:
            self.data["messages"] = messages[-MAX_HISTORY:]
        self.save()

    def get_recent(self, n: int = RECENT_WINDOW) -> list[dict]:
        messages = self.data.get("messages", [])
        return [{"role": m["role"], "content": m["content"]} for m in messages[-n:]]

    def clear(self):
        self.data = {"messages": [], "created_at": _now_iso()}
        self.save()


class ProjectNotesMemory:
    def __init__(self, filepath: Path = PROJECT_NOTES_FILE):
        self.filepath = filepath
        self.data = _read_json(filepath, {})

    def save(self):
        _atomic_save(self.filepath, self.data)

    def get_context_text(self) -> str:
        if not self.data:
            return ""
        lines = []
        for project_id, notes in self.data.items():
            lines.append(f"  - {project_id}: {notes}")
        return "Заметки о проектах:\n" + "\n".join(lines)


class MemoryManager:
    def __init__(self):
        self.profile = ProfileMemory()
        self.project_notes = ProjectNotesMemory()
        self._sessions: OrderedDict[str, SessionMemory] = OrderedDict()

    def get_session(self, session_id: str | None = None) -> tuple[str, SessionMemory]:
        if not session_id:
            session_id = _generate_session_id()
        if session_id not in self._sessions:
            self._evict_if_needed()
            self._sessions[session_id] = SessionMemory(session_id)
        self._sessions.move_to_end(session_id)
        return session_id, self._sessions[session_id]

    def drop_session(self, session_id: str):
        self._sessions.pop(session_id, None)

    def _evict_if_needed(self):
        while len(self._sessions) >= MAX_CACHED_SESSIONS:
            self._sessions.popitem(last=False)

    def build_system_prompt(self, projects: list) -> str:
        parts = [BASE_SYSTEM_PROMPT.strip()]

        if projects:
            projects_list = "\n".join(
                f"  - {p.project_id}: {p.display_name} ({'вкл' if p.enabled else 'выкл'})"
                for p in projects
            )
            parts.append("Текущие проекты в системе:\n" + projects_list)
        else:
            parts.append("Текущие проекты в системе:\n  (нет проектов)")

        profile_text = self.profile.get_context_text()
        if profile_text:
            parts.append(profile_text)

        notes_text = self.project_notes.get_context_text()
        if notes_text:
            parts.append(notes_text)

        return "\n\n".join(parts)


def _generate_session_id() -> str:
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
