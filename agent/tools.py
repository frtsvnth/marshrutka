from __future__ import annotations

from agent.models import ToolDefinition

from registry import load_projects
from storage import runs_store, schedules_store
from runner import run_project
from scheduler import add_schedule
from models import Schedule


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
                    "created_at": str(r.created_at),
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
]
