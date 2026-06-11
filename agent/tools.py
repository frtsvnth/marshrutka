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
    delete_runs,
)
from agent.capabilities import (
    discover_project_capabilities as _discover_project_capabilities,
    list_project_actions as _list_project_actions,
    invoke_project_action as _invoke_project_action,
    refresh_capability_registry as _refresh_capability_registry,
    fetch_json_url as _fetch_json_url,
)

import subprocess

from registry import load_projects
from storage import runs_store, schedules_store
from runner import run_project
from scheduler import add_schedule
from models import Schedule
from config import BASE_DIR, moscow_time


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


async def discover_project_capabilities(project_id: str = "") -> dict:
    try:
        pid = project_id.strip() or None
        return await _discover_project_capabilities(pid)
    except Exception as e:
        return {"error": f"Capability discovery failed: {e}"}


async def list_project_actions(project_id: str) -> dict:
    try:
        return await _list_project_actions(project_id)
    except Exception as e:
        return {"error": f"Failed to list project actions: {e}"}


async def invoke_project_action(action_id: str, params: dict = {}) -> dict:
    try:
        return await _invoke_project_action(action_id, params)
    except Exception as e:
        return {"error": f"Failed to invoke action: {e}"}


async def refresh_capability_registry() -> dict:
    try:
        return await _refresh_capability_registry()
    except Exception as e:
        return {"error": f"Failed to refresh registry: {e}"}


async def fetch_json_url(url: str) -> dict:
    try:
        return await _fetch_json_url(url)
    except Exception as e:
        return {"error": f"Failed to fetch JSON URL: {e}"}


def _git_run(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, cwd=BASE_DIR, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout.strip()
    except FileNotFoundError:
        raise RuntimeError("git not found")


def git_status() -> dict:
    try:
        status_text = _git_run("status", "--short")
        if not status_text:
            return {"status": "clean", "message": "Рабочая директория чиста, нет изменений"}
        lines = status_text.split("\n")
        staged = []
        unstaged = []
        untracked = []
        for line in lines:
            if not line.strip():
                continue
            code = line[:2]
            path = line[3:]
            if code == "??":
                untracked.append(path)
            elif " " not in code.strip():
                staged.append({"path": path, "status": code.strip()})
            else:
                unstaged.append({"path": path, "status": code.strip()})
        branch = _git_run("rev-parse", "--abbrev-ref", "HEAD")
        return {
            "status": "dirty",
            "branch": branch,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "total_changed": len(staged) + len(unstaged) + len(untracked),
            "preview": status_text,
        }
    except RuntimeError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Git status failed: {e}"}


def git_commit_push(message: str, description: str = "", confirm: bool = False) -> dict:
    try:
        branch = _git_run("rev-parse", "--abbrev-ref", "HEAD")

        status = git_status()
        if status.get("status") == "clean":
            return {"error": "Нет изменений для коммита"}

        if not confirm:
            return {
                "status": "preview",
                "branch": branch,
                "message": message,
                "description": description,
                "preview": status.get("preview", ""),
                "total_changed": status.get("total_changed", 0),
                "instruction": "Вызови с confirm=True для коммита и пуша.",
            }

        _git_run("add", "-A")
        full_message = message + ("\n\n" + description if description else "")
        _git_run("commit", "-m", full_message)
        _git_run("push")
        commit_hash = _git_run("rev-parse", "--short", "HEAD")
        return {
            "status": "pushed",
            "branch": branch,
            "commit": commit_hash,
            "message": message,
            "result": f"Изменения закоммичены ({commit_hash}) и отправлены в {branch}.",
        }
    except RuntimeError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Git commit/push failed: {e}"}


def navigate_to(url: str) -> dict:
    if not url.startswith(("/", "http://", "https://")):
        return {"error": "URL must be absolute path (e.g. /projects/story-to-video) or full URL"}
    return {
        "_navigation": url,
        "url": url,
        "status": "navigating",
        "message": "Перенаправляю на страницу...",
    }


def reload_page() -> dict:
    return {
        "_navigation": "reload",
        "status": "reloading",
        "message": "Обновляю страницу...",
    }


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
    "delete_runs": delete_runs,
    "git_status": git_status,
    "git_commit_push": git_commit_push,
    "navigate_to": navigate_to,
    "reload_page": reload_page,
    "discover_project_capabilities": discover_project_capabilities,
    "list_project_actions": list_project_actions,
    "invoke_project_action": invoke_project_action,
    "refresh_capability_registry": refresh_capability_registry,
    "fetch_json_url": fetch_json_url,
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
        name="delete_runs",
        description="Удалить запуски по фильтрам. Сначала вызови без confirm=True для предпросмотра, после подтверждения пользователя — с confirm=True.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID проекта для фильтрации (опционально)",
                },
                "statuses": {
                    "type": "string",
                    "description": "Статусы через запятую: sync_error, draft, linked, sync_pending, detached, cancelled_locally (опционально)",
                },
                "ids": {
                    "type": "string",
                    "description": "ID запусков через запятую (опционально)",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Подтверждение удаления. Сначала вызови без confirm, покажи preview пользователю, потом с confirm=True",
                },
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
    ToolDefinition(
        name="git_status",
        description="Показать текущее состояние git-репозитория: какие файлы изменены, добавлены, не отслеживаются. Используй перед git_commit_push, чтобы показать пользователю что будет закоммичено.",
        parameters={
            "type": "object",
            "properties": {},
        },
    ),
    ToolDefinition(
        name="git_commit_push",
        description="Закоммитить и запушить изменения в GitHub. Сначала вызови без confirm=True — покажет preview изменений. После подтверждения пользователя вызови с confirm=True. ВАЖНО: используй только после того, как пользователь подтвердил, что изменения правильные.",
        parameters={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Короткое описание коммита на русском или английском (что именно сделано)",
                },
                "description": {
                    "type": "string",
                    "description": "Подробное описание коммита (опционально)",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Подтверждение коммита и пуша. Сначала вызови без confirm, покажи preview пользователю, после подтверждения — с confirm=True",
                },
            },
            "required": ["message"],
        },
    ),
    ToolDefinition(
        name="discover_project_capabilities",
        description="Просканировать приложение и найти все доступные возможности (routes, publish bindings, UI actions, функции). Если указан project_id — только для этого проекта. Используй когда пользователь просит сделать действие, которого нет среди твоих обычных инструментов: опубликовать, отправить в очередь, запустить, удалить, ретрайнуть и т.д.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID проекта для сканирования (опционально). Если не указан — сканируется всё приложение.",
                },
            },
        },
    ),
    ToolDefinition(
        name="list_project_actions",
        description="Показать нормализованный список исполнимых действий для проекта. Возвращает actions, сгруппированные по intent (publish, enqueue, launch, retry, delete, edit, schedule).",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID проекта",
                },
            },
            "required": ["project_id"],
        },
    ),
    ToolDefinition(
        name="invoke_project_action",
        description="Попытаться выполнить найденное действие проекта. Для endpoint — делает HTTP-вызов. Для ui_form — эмулирует POST. Для destructive действий (publish/delete) требуется подтверждение.",
        parameters={
            "type": "object",
            "properties": {
                "action_id": {
                    "type": "string",
                    "description": "ID действия из registry (например, 'route.api.projects.project_id.publish.publish_youtube.post' или 'story-to-video.publish_youtube')",
                },
                "params": {
                    "type": "object",
                    "description": "Параметры для вызова: может содержать project_id, body, form_data, query_params",
                },
            },
            "required": ["action_id"],
        },
    ),
    ToolDefinition(
        name="refresh_capability_registry",
        description="Форсировать полный рескан capability registry — пересканировать routes, проекты, UI actions, код. Используй когда могли появиться новые возможности (после изменений в конфигах, после патчей файлов, при добавлении новых endpoint-ов).",
        parameters={
            "type": "object",
            "properties": {},
        },
    ),
    ToolDefinition(
        name="fetch_json_url",
        description="Загрузить JSON по URL. В отличие от fetch_url, этот инструмент понимает content-type и парсит JSON в structured объект. Используй для загрузки openapi.json, json-конфигов, API-ответов.",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL JSON-документа (например, http://localhost:9090/openapi.json)",
                },
            },
            "required": ["url"],
        },
    ),
    ToolDefinition(
        name="navigate_to",
        description="Перенаправить пользователя на указанную страницу в приложении. Используй когда нужно показать результат: после запуска пайплайна — на страницу запуска (/runs/{run_id}), после редактирования файла — обновить страницу через reload_page, после создания расписания — на проект и т.д.",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL для перенаправления. Абсолютный путь (например, /projects/story-to-video) или полный URL.",
                },
            },
            "required": ["url"],
        },
    ),
    ToolDefinition(
        name="reload_page",
        description="Обновить страницу браузера пользователя. Используй после apply_file_patch, update_config или других изменений, которые должны отобразиться сразу.",
        parameters={
            "type": "object",
            "properties": {},
        },
    ),
]
