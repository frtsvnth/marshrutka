from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from registry import load_projects
from storage import runs_store, schedules_store
from config import DATA_DIR, moscow_time

logger = logging.getLogger(__name__)

AGENT_JOBS_FILE = DATA_DIR / "agent" / "agent_jobs.json"


def _load_jobs() -> dict:
    if AGENT_JOBS_FILE.exists():
        try:
            return json.loads(AGENT_JOBS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"tasks": []}
    return {"tasks": []}


def _save_jobs(jobs: dict):
    AGENT_JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    AGENT_JOBS_FILE.write_text(
        json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def analyze_projects() -> dict:
    try:
        projects = load_projects()
        all_runs = runs_store.list()
        all_schedules = schedules_store.list()

        issues = []
        recommendations = []

        for p in projects:
            project_runs = [r for r in all_runs if r.project_id == p.project_id]
            project_schedules = [s for s in all_schedules if s.project_id == p.project_id]
            recent = sorted(project_runs, key=lambda r: r.created_at, reverse=True)

            if p.enabled and not project_schedules:
                recommendations.append(
                    f"Проект «{p.display_name}» включён, но нет расписания. "
                    "Рекомендуется создать cron-расписание."
                )

            if not recent:
                if p.enabled:
                    recommendations.append(
                        f"Проект «{p.display_name}» включён, но ещё не было запусков. "
                        "Рекомендуется запустить вручную."
                    )
                continue

            last_run = recent[0]
            now = datetime.utcnow()
            if last_run.created_at:
                run_time = last_run.created_at
                if run_time.tzinfo is not None:
                    run_time = run_time.replace(tzinfo=None)
                days_since = (now - run_time).total_seconds() / 86400
                if days_since > 7 and p.enabled:
                    recommendations.append(
                        f"Проект «{p.display_name}» не запускался {int(days_since)} дней. "
                        "Рекомендуется проверить состояние."
                    )

            failed = [r for r in recent[:5] if r.orchestration_status and "failed" in str(r.orchestration_status)]
            if len(failed) >= 3:
                issues.append(
                    f"Проект «{p.display_name}»: {len(failed)} из 5 последних запусков упали. "
                    "Требуется внимание."
                )

        return {
            "project_count": len(projects),
            "issues": issues,
            "recommendations": recommendations,
            "analyzed_at": _now_iso(),
        }
    except Exception as e:
        logger.exception("analyze_projects failed")
        return {"error": "Ошибка анализа проектов"}


def suggest_schedules(project_id: str = "") -> dict:
    try:
        projects = load_projects()
        if project_id:
            projects = [p for p in projects if p.project_id == project_id]

        suggestions = []
        for p in projects:
            existing = schedules_store.list()
            has_schedule = any(s.project_id == p.project_id for s in existing)
            if not has_schedule and p.enabled:
                suggestions.append({
                    "project_id": p.project_id,
                    "display_name": p.display_name,
                    "suggested_cron": "0 9 * * 1-5",
                    "suggested_title": f"Ежедневный запуск {p.display_name}",
                    "reason": "проект включён, но расписание отсутствует",
                })

        return {
            "project_count": len(projects),
            "suggestions": suggestions,
        }
    except Exception as e:
        logger.exception("suggest_schedules failed")
        return {"error": "Ошибка генерации предложений"}


def create_followup_task(title: str, description: str = "", task_type: str = "manual") -> dict:
    try:
        jobs = _load_jobs()
        tasks = jobs.setdefault("tasks", [])
        task = {
            "id": f"task_{len(tasks) + 1}_{int(datetime.now().timestamp())}",
            "title": title,
            "description": description,
            "type": task_type,
            "status": "pending",
            "created_at": _now_iso(),
        }
        tasks.append(task)
        _save_jobs(jobs)
        return {
            "task_id": task["id"],
            "title": title,
            "status": "created",
        }
    except Exception as e:
        logger.exception("create_followup_task failed")
        return {"error": "Ошибка создания задачи"}


def list_auto_tasks(status: str = "") -> dict:
    try:
        jobs = _load_jobs()
        tasks = jobs.get("tasks", [])
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        return {
            "task_count": len(tasks),
            "tasks": tasks,
        }
    except Exception as e:
        logger.exception("list_auto_tasks failed")
        return {"error": "Ошибка списка задач"}


def delete_runs(
    project_id: str = "",
    statuses: str = "",
    ids: str = "",
    confirm: bool = False,
) -> dict:
    try:
        all_runs = runs_store.list()
        if project_id:
            all_runs = [r for r in all_runs if r.project_id == project_id]
        if statuses:
            status_list = [s.strip() for s in statuses.split(",") if s.strip()]
            all_runs = [r for r in all_runs if r.orchestration_status and r.orchestration_status.value in status_list]
        if ids:
            id_list = [i.strip() for i in ids.split(",") if i.strip()]
            all_runs = [r for r in all_runs if r.run_id in id_list]

        if not all_runs:
            return {"deleted_count": 0, "preview": [], "message": "Нет запусков по заданным критериям"}

        preview = [
            {
                "run_id": r.run_id,
                "project_id": r.project_id,
                "status": r.orchestration_status.value if r.orchestration_status else "?",
                "created_at": moscow_time(r.created_at, "%d.%m.%Y %H:%M") if r.created_at else "?",
            }
            for r in all_runs
        ]

        if not confirm:
            return {
                "deleted_count": 0,
                "preview": preview,
                "message": f"Найдено {len(preview)} запусков. Вызови с confirm=True для удаления.",
            }

        deleted_ids = []
        for r in all_runs:
            runs_store.delete(r.run_id)
            deleted_ids.append(r.run_id)

        return {
            "deleted_count": len(deleted_ids),
            "preview": preview,
            "message": f"Удалено {len(deleted_ids)} запусков.",
        }

    except Exception as e:
        logger.exception("delete_runs failed")
        return {"error": f"Ошибка удаления запусков: {e}"}
