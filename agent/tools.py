from __future__ import annotations

from agent.models import ToolDefinition
from agent.web_tools import search_web, search_youtube
from agent.research import fetch_url, research_topic
from agent.file_tools import (
    read_project_file,
    search_project_code,
    propose_file_patch,
    apply_file_patch,
    update_config,
)
from agent.operator_tools import (
    analyze_projects,
    suggest_schedules,
    create_followup_task,
    list_auto_tasks,
)

from registry import load_projects
from storage import runs_store, schedules_store
from runner import run_project
from scheduler import add_schedule
from models import Schedule
from config import moscow_time


def count_words(text: str) -> dict:
    try:
        sentences = [s.strip() for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]
        return {
            "word_count": len(text.split()),
            "char_count": len(text),
            "sentence_count": len(sentences),
            "status": "ok",
        }
    except Exception as e:
        return {"error": str(e)}


def get_projects() -> dict:
    try:
        projects = load_projects()
        return {
            "projects": [
                {
                    "project_id": p.project_id,
                    "display_name": p.display_name,
                    "description": p.description,
                    "enabled": p.enabled,
                }
                for p in projects
            ],
            "count": len(projects),
        }
    except Exception as e:
        return {"error": str(e)}


def get_recent_runs(project_id: str = "", limit: int = 10) -> dict:
    try:
        runs = runs_store.list()
        if project_id:
            runs = [r for r in runs if r.project_id == project_id]
        runs.sort(key=lambda r: r.created_at, reverse=True)
        runs = runs[:limit]
        return {
            "runs": [
                {
                    "run_id": r.run_id,
                    "project_id": r.project_id,
                    "status": r.orchestration_status.value,
                    "created_at": moscow_time(r.created_at, "%d.%m.%Y %H:%M"),
                }
                for r in runs
            ],
            "count": len(runs),
        }
    except Exception as e:
        return {"error": str(e)}


async def run_pipeline(project_id: str, input_data: dict = {}) -> dict:
    try:
        from registry import get_project
        p = get_project(project_id)
        if not p:
            return {"error": f"Project not found: {project_id}"}
        run = await run_project(project_id, input_data)
        return {
            "run_id": run.run_id,
            "status": run.orchestration_status.value,
            "project_id": run.project_id,
        }
    except Exception as e:
        return {"error": str(e)}


def create_schedule(project_id: str, cron_expression: str, title: str = "") -> dict:
    try:
        from registry import get_project
        p = get_project(project_id)
        if not p:
            return {"error": f"Project not found: {project_id}"}
        sched = Schedule(
            project_id=project_id,
            cron_expression=cron_expression,
            title=title,
            enabled=True,
        )
        add_schedule(sched)
        return {
            "schedule_id": sched.schedule_id,
            "project_id": project_id,
            "cron": cron_expression,
            "status": "created",
        }
    except Exception as e:
        return {"error": str(e)}


def get_schedules(project_id: str = "") -> dict:
    try:
        schedules = schedules_store.list()
        if project_id:
            schedules = [s for s in schedules if s.project_id == project_id]
        return {
            "schedules": [
                {
                    "schedule_id": s.schedule_id,
                    "project_id": s.project_id,
                    "cron_expression": s.cron_expression,
                    "title": s.title,
                    "enabled": s.enabled,
                }
                for s in schedules
            ],
            "count": len(schedules),
        }
    except Exception as e:
        return {"error": str(e)}


TOOLS: dict[str, callable] = {
    "count_words": count_words,
    "get_projects": get_projects,
    "get_recent_runs": get_recent_runs,
    "run_pipeline": run_pipeline,
    "create_schedule": create_schedule,
    "get_schedules": get_schedules,
    "search_web": search_web,
    "search_youtube": search_youtube,
    "fetch_url": fetch_url,
    "research_topic": research_topic,
    "read_project_file": read_project_file,
    "search_project_code": search_project_code,
    "propose_file_patch": propose_file_patch,
    "apply_file_patch": apply_file_patch,
    "update_config": update_config,
    "analyze_projects": analyze_projects,
    "suggest_schedules": suggest_schedules,
    "create_followup_task": create_followup_task,
    "list_auto_tasks": list_auto_tasks,
}

TOOL_DEFINITIONS: list[ToolDefinition] = [
    ToolDefinition(
        name="count_words",
        description="Подсчитать количество слов, символов и предложений в тексте. Используй после генерации текста для проверки длины.",
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Текст для подсчёта слов",
                }
            },
            "required": ["text"],
        },
    ),
    ToolDefinition(
        name="get_projects",
        description="Получить список всех проектов в системе.",
        parameters={
            "type": "object",
            "properties": {},
        },
    ),
    ToolDefinition(
        name="get_recent_runs",
        description="Получить последние запуски. Можно отфильтровать по project_id.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID проекта для фильтрации (опционально)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Максимальное количество запусков",
                },
            },
        },
    ),
    ToolDefinition(
        name="run_pipeline",
        description="Запустить пайплайн проекта на удалённом сервере.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID проекта для запуска",
                },
                "input_data": {
                    "type": "object",
                    "description": "Входные данные для пайплайна",
                },
            },
            "required": ["project_id"],
        },
    ),
    ToolDefinition(
        name="create_schedule",
        description="Создать cron-расписание для проекта.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID проекта",
                },
                "cron_expression": {
                    "type": "string",
                    "description": "Cron-выражение (например, '0 9 * * 1-5')",
                },
                "title": {
                    "type": "string",
                    "description": "Название расписания (опционально)",
                },
            },
            "required": ["project_id", "cron_expression"],
        },
    ),
    ToolDefinition(
        name="get_schedules",
        description="Получить список расписаний. Можно отфильтровать по project_id.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID проекта для фильтрации (опционально)",
                },
            },
        },
    ),
    ToolDefinition(
        name="search_web",
        description="Искать информацию в интернете. Используй для поиска статей, новостей, референсов и любой свежей информации.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Поисковый запрос",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Количество результатов (1-10)",
                },
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="search_youtube",
        description="Искать видео на YouTube. Используй когда пользователь просит найти видео, ролики, ютуб-контент.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Поисковый запрос для поиска YouTube видео",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Количество результатов (1-10)",
                },
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="fetch_url",
        description="Загрузить содержимое веб-страницы по URL. Используй для чтения статей и документации.",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL страницы для загрузки",
                }
            },
            "required": ["url"],
        },
    ),
    ToolDefinition(
        name="research_topic",
        description="Провести глубокое исследование темы: делает поиск, загружает несколько страниц и возвращает контент. Используй когда нужно изучить тему подробно.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Тема для исследования",
                },
                "num_queries": {
                    "type": "integer",
                    "description": "Количество результатов поиска (1-5)",
                },
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="read_project_file",
        description="Прочитать файл или директорию в проекте. Путь относительно корня проекта.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Путь к файлу относительно корня проекта",
                }
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        name="search_project_code",
        description="Найти вхождение текста в файлах проекта. Поддерживает .py, .html, .js, .css, .json, .md.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Текст для поиска",
                },
                "include": {
                    "type": "string",
                    "description": "Маска файлов через запятую (по умолчанию *.py,*.html,*.js,*.css,*.json,*.md)",
                },
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="propose_file_patch",
        description="Подготовить файл к редактированию: возвращает текущее содержимое и инструкцию. Используй перед apply_file_patch. НЕ применяет изменения, только показывает.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Путь к файлу относительно корня проекта",
                },
                "instruction": {
                    "type": "string",
                    "description": "Описание желаемого изменения",
                },
            },
            "required": ["path", "instruction"],
        },
    ),
    ToolDefinition(
        name="apply_file_patch",
        description="Применить изменения к файлу. ВАЖНО: используй только после propose_file_patch и получения подтверждения от пользователя.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Путь к файлу относительно корня проекта",
                },
                "patch": {
                    "type": "string",
                    "description": "Новое полное содержимое файла",
                },
            },
            "required": ["path", "patch"],
        },
    ),
    ToolDefinition(
        name="update_config",
        description="Обновить значение в .env конфиге проекта.",
        parameters={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Имя переменной (например, ROUTERAI_MODEL)",
                },
                "value": {
                    "type": "string",
                    "description": "Новое значение",
                },
            },
            "required": ["key", "value"],
        },
    ),
    ToolDefinition(
        name="analyze_projects",
        description="Проанализировать состояние всех проектов: проверить запуски, расписания, найти проблемы и дать рекомендации.",
        parameters={
            "type": "object",
            "properties": {},
        },
    ),
    ToolDefinition(
        name="suggest_schedules",
        description="Предложить cron-расписания для проектов, у которых их нет.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID проекта (опционально, для фильтрации)",
                }
            },
        },
    ),
    ToolDefinition(
        name="create_followup_task",
        description="Создать followup-задачу для отслеживания. Используй когда договорились о действии на будущее.",
        parameters={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Название задачи",
                },
                "description": {
                    "type": "string",
                    "description": "Описание задачи",
                },
                "task_type": {
                    "type": "string",
                    "description": "Тип задачи (manual, health_check, research_watch)",
                },
            },
            "required": ["title"],
        },
    ),
    ToolDefinition(
        name="list_auto_tasks",
        description="Получить список созданных авто-задач.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Фильтр по статусу (pending, completed, cancelled)",
                }
            },
        },
    ),
    ToolDefinition(
        name="remember_fact",
        description="Запомнить факт о пользователе. Используй когда пользователь говорит «запомни» или просит сохранить информацию о себе.",
        parameters={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Ключ факта (например, preferred_style, name, working_hours)",
                },
                "value": {
                    "type": "string",
                    "description": "Значение факта",
                },
            },
            "required": ["key", "value"],
        },
    ),
    ToolDefinition(
        name="remember_project_note",
        description="Запомнить заметку о проекте. Используй когда пользователь говорит о проекте важную информацию.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID проекта",
                },
                "key": {
                    "type": "string",
                    "description": "Ключ заметки",
                },
                "value": {
                    "type": "string",
                    "description": "Содержание заметки",
                },
            },
            "required": ["project_id", "key", "value"],
        },
    ),
    ToolDefinition(
        name="list_memories",
        description="Показать сохранённые воспоминания. Можно отфильтровать по области.",
        parameters={
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "Область: user (факты), projects (заметки о проектах), decisions (журнал решений), all (всё)",
                }
            },
        },
    ),
    ToolDefinition(
        name="search_memories",
        description="Поиск по долговременной памяти. Ищет среди фактов о пользователе и заметок о проектах.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Текст для поиска",
                }
            },
            "required": ["query"],
        },
    ),
]
