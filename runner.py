from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from models import (
    Run,
    OrchestrationStatus,
    RemoteExecutionStatus,
)
from registry import get_project
from storage import runs_store
from remote_sync import fetch_remote_jobs


async def http_post(url: str, json_body: dict) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=json_body)
        resp.raise_for_status()
        return resp.json()


async def submit_remote_job(
    api_url: str,
    run_endpoint: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    url = f"{api_url.rstrip('/')}{run_endpoint}"
    return await http_post(url, payload)


async def run_project(project_id: str, input_data: dict[str, Any], queue_item_id: str | None = None) -> Run:
    project = get_project(project_id)
    if not project:
        raise ValueError(f"Project not found: {project_id}")

    run = Run(
        project_id=project_id,
        orchestration_status=OrchestrationStatus.submitting,
        remote_status=RemoteExecutionStatus.unknown,
        input=input_data,
        submitted_at=datetime.utcnow(),
        queue_item_id=queue_item_id,
    )
    runs_store.save(run)

    api_url = project.integration.api_url or project.config.get("api_url", "")
    run_endpoint = project.integration.run_endpoint or project.integration.jobs_list_endpoint

    if api_url and run_endpoint:
        try:
            payload = dict(input_data)
            payload = _clean_payload(project_id, payload)
            result = await submit_remote_job(api_url, run_endpoint, payload)
            ext_job_id = result.get("job_id") or result.get("id") or ""

            if ext_job_id:
                run.remote_job_id = ext_job_id
                run.orchestration_status = OrchestrationStatus.linked
                run.remote_status = _map_remote_status(result.get("status", ""))
                run.submit_response = result
            else:
                run.orchestration_status = OrchestrationStatus.detached
                run.remote_status = RemoteExecutionStatus.unknown
                run.submit_response = result
                run.sync_error = f"Remote did not return job_id. Response: {result.get('status', '?')}"

        except Exception as e:
            run.orchestration_status = OrchestrationStatus.sync_error
            run.remote_status = RemoteExecutionStatus.unknown
            run.sync_error = f"Submit failed: {e}"
    else:
        run.orchestration_status = OrchestrationStatus.detached
        run.remote_status = RemoteExecutionStatus.unknown
        run.sync_error = "No API URL configured"

    run.updated_at = datetime.utcnow()
    runs_store.save(run)

    try:
        await fetch_remote_jobs(project.integration, project_id)
    except Exception:
        pass

    return run


def _clean_payload(project_id: str, payload: dict) -> dict:
    cleaned = {}
    for key, value in payload.items():
        if value == "" or value is None:
            continue
        key_lower = key.lower()
        if key_lower in ("publish_to_telegram", "telegram_enabled", "landscape", "post_to_telegram"):
            cleaned[key] = value in ("true", "on", "1", "yes", True)
        elif key_lower == "queries":
            if isinstance(value, str) and "," in value:
                cleaned[key] = [q.strip() for q in value.split(",") if q.strip()]
            elif isinstance(value, str) and value:
                cleaned[key] = [value]
            elif isinstance(value, list):
                cleaned[key] = value
        elif key_lower in ("speech_rate",):
            try:
                cleaned[key] = float(value)
            except (ValueError, TypeError):
                cleaned[key] = value
        else:
            cleaned[key] = value
    return cleaned


def _map_remote_status(status_str: str) -> RemoteExecutionStatus:
    mapping = {
        "pending": RemoteExecutionStatus.pending,
        "queued": RemoteExecutionStatus.pending,
        "running": RemoteExecutionStatus.running,
        "in_progress": RemoteExecutionStatus.running,
        "success": RemoteExecutionStatus.success,
        "completed": RemoteExecutionStatus.success,
        "done": RemoteExecutionStatus.success,
        "failed": RemoteExecutionStatus.failed,
        "error": RemoteExecutionStatus.failed,
        "partial": RemoteExecutionStatus.failed,
        "cancelled": RemoteExecutionStatus.cancelled,
        "canceled": RemoteExecutionStatus.cancelled,
    }
    return mapping.get(status_str.lower(), RemoteExecutionStatus.unknown)
