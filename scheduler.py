from __future__ import annotations

import asyncio
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from registry import get_project
from storage import schedules_store, runs_store
from models import Run, OrchestrationStatus, RemoteExecutionStatus, Schedule
from runner import run_project

scheduler = AsyncIOScheduler()


async def execute_scheduled_run(schedule_id: str):
    sched = schedules_store.get(schedule_id, "schedule_id")
    if not sched or not sched.enabled:
        return
    project = get_project(sched.project_id)
    if not project or not project.enabled:
        return
    try:
        run = await run_project(sched.project_id, sched.input)
        sched.last_run_at = datetime.utcnow()
        schedules_store.save(sched)
    except Exception as e:
        print(f"[scheduler] Run failed for schedule {schedule_id}: {e}")


def schedule_job(sched: Schedule):
    if not sched.enabled:
        return
    trigger = CronTrigger.from_crontab(sched.cron_expression)
    scheduler.add_job(
        execute_scheduled_run,
        trigger=trigger,
        args=[sched.schedule_id],
        id=sched.schedule_id,
        replace_existing=True,
    )


def reload_schedules():
    for job_id in scheduler.get_jobs():
        scheduler.remove_job(job_id.job_id)
    for sched in schedules_store.list():
        schedule_job(sched)


def add_schedule(sched: Schedule):
    schedules_store.save(sched)
    schedule_job(sched)


def remove_schedule(schedule_id: str):
    schedules_store.delete(schedule_id, "schedule_id")
    if scheduler.get_job(schedule_id):
        scheduler.remove_job(schedule_id)
