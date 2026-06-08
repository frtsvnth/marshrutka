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
USER_FACTS_FILE = AGENT_DIR / "user_facts.json"
PROJECT_MEMORY_FILE = AGENT_DIR / "project_memory.json"
DECISIONS_LOG_FILE = AGENT_DIR / "decisions_log.jsonl"
RESEARCH_CACHE_FILE = AGENT_DIR / "research_cache.json"

AGENT_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

MAX_HISTORY = 50
RECENT_WINDOW = 15
MAX_CACHED_SESSIONS = 100

BASE_SYSTEM_PROMPT = """
Ты — Маршал, AI-ассистент инструмента Marshrutka для запуска контентных пайплайнов.

Твои возможности:
- Отвечать на вопросы про контент (написать текст, придумать тему, проверить длину)
- Работать с проектами: смотреть список, последние запуски, статусы
- Запускать пайплайны проектов через инструменты
- Создавать расписания для проектов
- Проверять результаты своей работы через инструменты (харнесс-цикл)
- Искать информацию в интернете через search_web, fetch_url, research_topic
- Искать видео на YouTube через search_youtube
- Запоминать информацию о пользователе и проектах через remember_fact, remember_project_note
- Анализировать состояние проектов через analyze_projects
- Читать и редактировать файлы проекта через файловые инструменты
- Создавать followup-задачи

ВАЖНО:
- Когда нужно выполнить действие — используй инструменты.
- После генерации текста вызови count_words, убедись в правильности длины.
- Если длина не совпадает — скорректируй текст и проверь снова.
- Не выдумывай информацию о проектах — используй get_projects для получения актуальных данных.
- Не говори "у меня нет доступа в интернет" — у тебя есть search_web, fetch_url, research_topic.
- Если просит найти ссылки, статьи, новости, референсы — используй search_web или research_topic.
- Если пользователь говорит «запомни» — используй remember_fact или remember_project_note.
- Используй информацию из долговременной памяти (факты о пользователе, заметки о проектах) при ответах.
- Перед редактированием файлов сначала используй propose_file_patch, покажи изменения, и только после подтверждения применяй apply_file_patch.
- Не выдумывай ссылки. Используй только реальные результаты из инструментов.
- Если пользователь хочет получить рекомендации по проектам — используй analyze_projects.
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


class UserFactsMemory:
    def __init__(self, filepath: Path = USER_FACTS_FILE):
        self.filepath = filepath
        self.data = _read_json(filepath, [])

    def save(self):
        _atomic_save(self.filepath, self.data)

    def add_fact(self, key: str, value: str):
        existing = [f for f in self.data if f.get("key") == key]
        if existing:
            existing[0]["value"] = value
            existing[0]["updated_at"] = _now_iso()
        else:
            self.data.append({
                "key": key,
                "value": value,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            })
        self.save()

    def get_fact(self, key: str) -> str | None:
        for f in self.data:
            if f.get("key") == key:
                return f.get("value")
        return None

    def search(self, query: str) -> list[dict]:
        q = query.lower()
        return [
            f for f in self.data
            if q in f.get("key", "").lower() or q in f.get("value", "").lower()
        ]

    def get_context_text(self) -> str:
        if not self.data:
            return ""
        lines = ["Факты о пользователе:"]
        for f in self.data:
            lines.append(f"  - {f['key']}: {f['value']}")
        return "\n".join(lines)


class ProjectMemoryStore:
    def __init__(self, filepath: Path = PROJECT_MEMORY_FILE):
        self.filepath = filepath
        self.data = _read_json(filepath, {})

    def save(self):
        _atomic_save(self.filepath, self.data)

    def add_note(self, project_id: str, key: str, value: str):
        project = self.data.setdefault(project_id, {})
        project[key] = value
        self.save()

    def get_project_memory(self, project_id: str) -> dict:
        return self.data.get(project_id, {})

    def search(self, query: str) -> list[dict]:
        q = query.lower()
        results = []
        for pid, notes in self.data.items():
            for key, value in notes.items():
                if q in pid.lower() or q in key.lower() or q in value.lower():
                    results.append({
                        "project_id": pid,
                        "key": key,
                        "value": value,
                    })
        return results

    def get_context_text(self) -> str:
        if not self.data:
            return ""
        lines = ["Знания о проектах:"]
        for pid, notes in self.data.items():
            lines.append(f"  {pid}:")
            for k, v in notes.items():
                lines.append(f"    - {k}: {v}")
        return "\n".join(lines)


class DecisionsLog:
    def __init__(self, filepath: Path = DECISIONS_LOG_FILE):
        self.filepath = filepath

    def log(self, user_request: str, recommendation: str, action: str, result: str = ""):
        entry = {
            "timestamp": _now_iso(),
            "user_request": user_request,
            "recommendation": recommendation,
            "action": action,
            "result": result,
        }
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("Failed to write decision log: %s", e)

    def get_recent(self, n: int = 10) -> list[dict]:
        if not self.filepath.exists():
            return []
        try:
            lines = self.filepath.read_text(encoding="utf-8").strip().split("\n")
            entries = []
            for line in lines[-n:]:
                if line.strip():
                    entries.append(json.loads(line))
            return entries
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read decisions log: %s", e)
            return []


class ResearchCache:
    def __init__(self, filepath: Path = RESEARCH_CACHE_FILE):
        self.filepath = filepath
        self.data = _read_json(filepath, [])

    def save(self):
        _atomic_save(self.filepath, self.data)

    def get(self, query: str) -> dict | None:
        q = query.lower().strip()
        for entry in self.data:
            if entry.get("query", "").lower().strip() == q:
                return entry
        return None

    def put(self, query: str, results: dict):
        self.data = [e for e in self.data if e.get("query", "").lower().strip() != query.lower().strip()]
        self.data.append({
            "query": query,
            "results": results,
            "cached_at": _now_iso(),
        })
        if len(self.data) > 50:
            self.data = self.data[-50:]
        self.save()


class MemoryManager:
    def __init__(self):
        self.profile = ProfileMemory()
        self.project_notes = ProjectNotesMemory()
        self.user_facts = UserFactsMemory()
        self.project_memory = ProjectMemoryStore()
        self.decisions = DecisionsLog()
        self.research_cache = ResearchCache()
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

        facts_text = self.user_facts.get_context_text()
        if facts_text:
            parts.append(facts_text)

        pm_text = self.project_memory.get_context_text()
        if pm_text:
            parts.append(pm_text)

        return "\n\n".join(parts)

    def remember_fact(self, key: str, value: str) -> dict:
        self.user_facts.add_fact(key, value)
        return {"status": "remembered", "key": key, "value": value}

    def remember_project_note(self, project_id: str, key: str, value: str) -> dict:
        self.project_memory.add_note(project_id, key, value)
        return {"status": "remembered", "project_id": project_id, "key": key}

    def list_memories(self, scope: str = "user") -> dict:
        if scope == "user":
            return {"scope": "user", "facts": self.user_facts.data}
        elif scope == "projects":
            return {"scope": "projects", "memories": self.project_memory.data}
        elif scope == "decisions":
            return {"scope": "decisions", "entries": self.decisions.get_recent(20)}
        return {"scope": "all", "facts": self.user_facts.data, "project_memories": self.project_memory.data}

    def search_memories(self, query: str) -> dict:
        user_results = self.user_facts.search(query)
        project_results = self.project_memory.search(query)
        return {
            "query": query,
            "user_facts": user_results,
            "project_memories": project_results,
        }


def _generate_session_id() -> str:
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
