from __future__ import annotations

import json
import tempfile
from pathlib import Path

SYSTEM_PROMPT_TEMPLATE = """
Ты — AI-ассистент Маршрутки, инструмента для запуска контентных пайплайнов.
Твоё имя — Маршал. Ты работаешь через ROUTERAI.RU с моделью deepseek-v4-flash.

Текущие проекты в системе:
{projects_list}

Что ты умеешь:
- Отвечать на вопросы про контент (написать текст, придумать тему, проверить длину)
- Работать с проектами: смотреть список, последние запуски, статусы
- Запускать пайплайны проектов через инструменты
- Создавать расписания для проектов
- Проверять результаты своей работы через инструменты (харнесс-цикл)

ВАЖНО: Когда тебе нужно выполнить действие или проверить что-то — используй инструменты.
Ты ОБЯЗАН использовать инструмент count_words когда пользователь просит написать текст
определённой длины. После генерации текста вызови count_words, убедись в правильности,
и если длина не совпадает — скорректируй текст и проверь снова.

{user_context_section}

Формат вызова инструмента — только если нужен инструмент, вставь в свой ответ JSON-блок:
<tool_call>
{{"tool": "имя_инструмента", "args": {{"аргумент": "значение"}}}}
</tool_call>

После получения результата инструмента продолжи ответ. Можно делать несколько вызовов.
Финальный ответ пользователю — обычный текст без тегов tool_call.
"""


class AgentMemory:
    def __init__(self, memory_file: Path):
        self.memory_file = memory_file
        if self.memory_file.exists():
            self.data = json.loads(self.memory_file.read_text())
        else:
            self.data = {
                "user_context": {"name": "", "preferences": [], "notes": []},
                "project_notes": {},
                "conversation_history": [],
            }
            self.save()

    def save(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(self.memory_file.parent),
            prefix=".agent_memory_tmp_",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        )
        try:
            json.dump(self.data, tmp, indent=2, ensure_ascii=False, default=str)
            tmp.close()
            Path(tmp.name).replace(self.memory_file)
        except Exception:
            Path(tmp.name).unlink(missing_ok=True)
            raise

    def get_system_prompt(self, projects: list) -> str:
        if projects:
            projects_list = "\n".join(
                f"  - {p.project_id}: {p.display_name} ({'вкл' if p.enabled else 'выкл'})"
                for p in projects
            )
        else:
            projects_list = "  (нет проектов)"

        ctx = self.data.get("user_context", {})
        parts = []
        if ctx.get("name"):
            parts.append(f"Имя пользователя: {ctx['name']}")
        if ctx.get("preferences"):
            parts.append(f"Предпочтения: {', '.join(ctx['preferences'])}")
        if ctx.get("notes"):
            parts.append(f"Заметки: {'; '.join(ctx['notes'])}")
        user_context_section = (
            "Известная информация о пользователе:\n" + "\n".join(parts)
            if parts
            else ""
        )

        return SYSTEM_PROMPT_TEMPLATE.format(
            projects_list=projects_list,
            user_context_section=user_context_section,
        ).strip()

    def add_to_history(self, role: str, content: str):
        self.data.setdefault("conversation_history", []).append(
            {"role": role, "content": content}
        )
        if len(self.data["conversation_history"]) > 20:
            self.data["conversation_history"] = self.data["conversation_history"][-20:]

    def update_user_context(self, key: str, value):
        self.data.setdefault("user_context", {})[key] = value
        self.save()

    def get_recent_history(self, n: int = 10) -> list[dict]:
        history = self.data.get("conversation_history", [])
        return history[-n:]
