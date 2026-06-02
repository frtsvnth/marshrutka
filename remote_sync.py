from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from models import (
    RemoteJobSummary,
    RemoteJobDetails,
    RemoteJobRef,
    SyncSnapshot,
    SyncSource,
    ProjectIntegration,
    OrchestrationStatus,
    RemoteExecutionStatus,
    Run,
)
from storage import runs_store


async def fetch_remote_jobs(
    integration: ProjectIntegration,
    project_id: str,
) -> SyncSnapshot:
    if not integration.api_url:
        return SyncSnapshot(
            project_id=project_id,
            remote_jobs=[],
            synced_at=datetime.utcnow(),
            error="API URL not configured",
        )
    try:
        url = f"{integration.api_url.rstrip('/')}{integration.jobs_list_endpoint}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return SyncSnapshot(
            project_id=project_id,
            remote_jobs=[],
            synced_at=datetime.utcnow(),
            error=str(e),
        )

    if isinstance(data, dict) and "items" in data:
        items = data["items"]
    elif isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("jobs", data.get("items", [data]))
    else:
        items = []

    remote_jobs = []
    for item in items:
        if isinstance(item, str):
            continue
        summary = _map_to_remote_summary(item, project_id)
        if summary:
            remote_jobs.append(summary)

    snapshot = SyncSnapshot(
        project_id=project_id,
        remote_jobs=remote_jobs,
        synced_at=datetime.utcnow(),
    )

    _link_local_runs(project_id, snapshot)

    return snapshot


async def sync_run_status(
    run: Run,
    integration: ProjectIntegration,
) -> RemoteJobRef | None:
    if not run.remote_job_id or not integration.api_url:
        return None

    ref = await fetch_remote_job_ref(integration, run.project_id, run.remote_job_id)
    if ref is None:
        run.orchestration_status = OrchestrationStatus.sync_error
        run.sync_error = f"Failed to fetch remote job {run.remote_job_id}"
        run.updated_at = datetime.utcnow()
        runs_store.save(run)
        return None

    run.remote_status = _map_remote_status(ref.remote_status)
    run.last_sync_at = ref.last_synced_at
    run.sync_error = None
    run.orchestration_status = OrchestrationStatus.linked
    run.updated_at = datetime.utcnow()
    runs_store.save(run)
    return ref


async def fetch_artifact(
    integration: ProjectIntegration,
    remote_job_id: str,
    artifact_key: str,
) -> tuple[bytes, str] | None:
    if not integration.api_url:
        return None
    try:
        path = integration.artifacts_endpoint.replace("{job_id}", remote_job_id).replace("{key}", artifact_key)
        url = f"{integration.api_url.rstrip('/')}{path}"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "application/octet-stream")
            return resp.content, content_type
    except Exception:
        return None


async def fetch_remote_job_details(
    integration: ProjectIntegration,
    project_id: str,
    remote_job_id: str,
) -> RemoteJobDetails | None:
    if not integration.api_url:
        return None
    try:
        path = integration.job_detail_endpoint.replace("{job_id}", remote_job_id)
        url = f"{integration.api_url.rstrip('/')}{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None

    return RemoteJobDetails(
        remote_job_id=remote_job_id,
        project_id=project_id,
        status=str(data.get("status", "unknown")),
        source=SyncSource.remote,
        started_at=_parse_dt(data.get("started_at") or data.get("created_at")),
        finished_at=_parse_dt(data.get("finished_at") or data.get("completed_at")),
        input_data=data.get("input", data.get("payload", {})),
        steps=data.get("steps", []),
        progress=data.get("progress") or {},
        artifacts=data.get("artifacts") or {},
        metadata=data.get("metadata") or {},
        logs=data.get("log") or data.get("run_log") or "",
        warnings=data.get("warnings") or [],
        job_response=data,
        synced_at=datetime.utcnow(),
    )


async def fetch_remote_job_ref(
    integration: ProjectIntegration,
    project_id: str,
    remote_job_id: str,
) -> RemoteJobRef | None:
    if not integration.api_url:
        return None
    try:
        path = integration.job_detail_endpoint.replace("{job_id}", remote_job_id)
        url = f"{integration.api_url.rstrip('/')}{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None

    return RemoteJobRef(
        project_id=project_id,
        external_job_id=remote_job_id,
        remote_status=str(data.get("status", "unknown")),
        started_at=_parse_dt(data.get("started_at") or data.get("created_at")),
        finished_at=_parse_dt(data.get("finished_at") or data.get("completed_at")),
        steps=data.get("steps") or [],
        progress=data.get("progress") or {},
        artifacts=data.get("artifacts") or {},
        metadata=data.get("metadata") or {},
        logs=data.get("log") or data.get("run_log") or "",
        warnings=data.get("warnings") or [],
        job_response=data,
        last_synced_at=datetime.utcnow(),
    )


def _link_local_runs(project_id: str, snapshot: SyncSnapshot):
    local_runs = [r for r in runs_store.list() if r.project_id == project_id]

    remote_by_id = {rj.remote_job_id: rj for rj in snapshot.remote_jobs}

    for run in local_runs:
        changed = False

        if run.remote_job_id and run.remote_job_id in remote_by_id:
            rj = remote_by_id[run.remote_job_id]
            new_status = _map_remote_status(rj.status)
            if run.remote_status != new_status:
                run.remote_status = new_status
                changed = True
            if run.orchestration_status != OrchestrationStatus.linked:
                run.orchestration_status = OrchestrationStatus.linked
                changed = True
            run.last_sync_at = snapshot.synced_at
            run.sync_error = None
            changed = True

        elif run.remote_job_id and run.remote_job_id not in remote_by_id:
            if run.orchestration_status == OrchestrationStatus.linked:
                run.orchestration_status = OrchestrationStatus.detached
                run.sync_error = "Remote job no longer found on server"
                changed = True

        if changed:
            run.updated_at = datetime.utcnow()
            runs_store.save(run)


def _map_to_remote_summary(item: dict, project_id: str) -> RemoteJobSummary | None:
    remote_id = item.get("job_id") or item.get("id") or ""
    if not remote_id:
        return None

    status = str(item.get("status", "unknown"))
    started = _parse_dt(item.get("started_at") or item.get("created_at"))
    finished = _parse_dt(item.get("finished_at") or item.get("completed_at"))

    input_summary = _derive_input_summary(item)

    return RemoteJobSummary(
        remote_job_id=remote_id,
        project_id=project_id,
        status=status,
        source=SyncSource.remote,
        started_at=started,
        finished_at=finished,
        title=remote_id,
        input_summary=input_summary,
        has_details=True,
        synced_at=datetime.utcnow(),
    )


def _derive_input_summary(item: dict) -> str:
    input_data = item.get("input", item.get("payload", {}))
    if input_data:
        text = input_data.get("news_text") or input_data.get("text") or input_data.get("title") or input_data.get("url") or ""
        if text and len(text) > 80:
            text = text[:80] + "..."
        if text:
            return text

    metadata = item.get("metadata", {})
    if metadata:
        text = metadata.get("input_text") or metadata.get("title") or ""
        if text and len(text) > 80:
            text = text[:80] + "..."
        if text:
            return text

    return _summarize_input(input_data)


def _summarize_input(input_data: dict) -> str:
    if not input_data:
        return ""
    text = input_data.get("news_text") or input_data.get("text") or input_data.get("title") or ""
    url = input_data.get("url") or ""
    if text and len(text) > 80:
        text = text[:80] + "..."
    return text or url or str(list(input_data.keys()))


def _parse_dt(val: Any) -> datetime | None:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(val, str):
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
        ):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
    return None


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


def build_merged_runs(
    project_id: str,
    local_runs: list,
    remote_snapshot: SyncSnapshot | None,
) -> list[dict]:
    seen = {}
    for r in local_runs:
        key = r.remote_job_id or r.run_id
        seen[key] = {
            "id": r.run_id,
            "remote_id": r.remote_job_id or "",
            "orchestration_status": r.orchestration_status.value,
            "remote_status": r.remote_status.value,
            "source": "local",
            "started_at": r.submitted_at or r.created_at,
            "finished_at": None,
            "input": r.input,
            "input_summary": _summarize_input(r.input),
            "has_details": bool(r.remote_job_id),
            "synced_at": r.last_sync_at or r.updated_at,
            "local_run_id": r.run_id,
            "sync_error": r.sync_error,
        }

    if remote_snapshot:
        for rj in remote_snapshot.remote_jobs:
            key = rj.remote_job_id
            if key in seen:
                seen[key]["source"] = "merged"
                seen[key]["remote_id"] = rj.remote_job_id
                seen[key]["remote_status"] = rj.status
                if not seen[key].get("finished_at") and rj.finished_at:
                    seen[key]["finished_at"] = rj.finished_at
                if rj.started_at and not seen[key].get("started_at"):
                    seen[key]["started_at"] = rj.started_at
                seen[key]["synced_at"] = rj.synced_at or remote_snapshot.synced_at
            else:
                seen[key] = {
                    "id": "",
                    "remote_id": rj.remote_job_id,
                    "orchestration_status": "",
                    "remote_status": rj.status,
                    "source": "remote",
                    "started_at": rj.started_at,
                    "finished_at": rj.finished_at,
                    "input": {},
                    "title": rj.title,
                    "input_summary": rj.input_summary,
                    "has_details": rj.has_details,
                    "synced_at": rj.synced_at or remote_snapshot.synced_at,
                    "local_run_id": None,
                    "sync_error": None,
                }

    result = list(seen.values())
    result.sort(key=lambda x: (
        x.get("started_at") or x.get("synced_at") or datetime.min
    ), reverse=True)
    return result
