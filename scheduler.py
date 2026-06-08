from __future__ import annotations

import asyncio
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from registry import get_project
from storage import schedules_store, queue_store
from models import Schedule, QueueItemStatus
from runner import run_project

scheduler = AsyncIOScheduler()


async def execute_scheduled_run(schedule_id: str):
    sched = schedules_store.get(schedule_id, "schedule_id")
    if not sched or not sched.enabled:
        return
    project = get_project(sched.project_id)
    if not project or not project.enabled:
        return
    items = queue_store.list_items(sched.project_id)
    queued = sorted(
        [i for i in items if i.status == QueueItemStatus.queued],
        key=lambda i: i.position,
    )
    if not queued:
        print(f"[scheduler] Schedule {schedule_id}: queue is empty, no-op")
        sched.last_run_at = datetime.utcnow()
        schedules_store.save(sched)
        return
    candidate = queued[0]
    if not candidate.payload:
        candidate.status = QueueItemStatus.failed
        candidate.last_error = "Empty payload — cannot launch"
        candidate.updated_at = datetime.utcnow()
        queue_store.save_item(sched.project_id, candidate)
        sched.last_run_at = datetime.utcnow()
        schedules_store.save(sched)
        return
    try:
        candidate.status = QueueItemStatus.launching
        candidate.updated_at = datetime.utcnow()
        queue_store.save_item(sched.project_id, candidate)
        run = await run_project(sched.project_id, candidate.payload, queue_item_id=candidate.queue_item_id)
        candidate.status = QueueItemStatus.launched
        candidate.last_launch_at = datetime.utcnow()
        candidate.last_run_id = run.run_id
        candidate.last_remote_job_id = run.remote_job_id
        candidate.last_error = ""
        candidate.launch_history.append({
            "run_id": run.run_id,
            "remote_job_id": run.remote_job_id,
            "launched_at": candidate.last_launch_at.isoformat(),
            "remote_status": run.remote_status.value,
            "trigger": "schedule",
        })
        candidate.updated_at = datetime.utcnow()
        queue_store.save_item(sched.project_id, candidate)
        sched.last_run_at = datetime.utcnow()
        schedules_store.save(sched)
    except Exception as e:
        candidate.status = QueueItemStatus.failed
        candidate.last_error = f"Scheduled launch failed: {e}"
        candidate.updated_at = datetime.utcnow()
        queue_store.save_item(sched.project_id, candidate)
        print(f"[scheduler] Queue item {candidate.queue_item_id} failed: {e}")
        sched.last_run_at = datetime.utcnow()
        schedules_store.save(sched)


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
        scheduler.remove_job(job_id.id)
    for sched in schedules_store.list():
        schedule_job(sched)


def add_schedule(sched: Schedule):
    schedules_store.save(sched)
    schedule_job(sched)


def remove_schedule(schedule_id: str):
    schedules_store.delete(schedule_id, "schedule_id")
    if scheduler.get_job(schedule_id):
        scheduler.remove_job(schedule_id)
