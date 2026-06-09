from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import TEMPLATES_DIR
from models import (
    Schedule, Project, ProjectInputField, JobDefinition, ProjectPublishTarget,
    JobType, PublishProfile, PublishPlatform, PublishRequest, ProjectIntegration,
    ProjectPublishBinding, PLATFORM_LABELS, PLATFORM_SHORT_CAPABLE,
    OrchestrationStatus, RemoteExecutionStatus,
    ORCHESTRATION_LABELS, REMOTE_STATUS_LABELS,
    resolve_artifact_filename, get_artifact_extension,
    is_previewable, get_preview_kind, sanitize_filename,
    PREVIEW_CONTENT_TYPES, resolve_primary_artifact,
    QueueItem, QueueItemStatus, QUEUE_STATUS_LABELS, QueueItemSource,
    ProjectDefaults,
)
from registry import load_projects, get_project, get_enabled_jobs, save_project
from storage import runs_store, schedules_store, profiles_store, publish_requests_store, queue_store, content_memory_store
from runner import run_project
from scheduler import add_schedule, remove_schedule
from remote_sync import fetch_remote_jobs, fetch_remote_job_details, sync_run_status, build_merged_runs

router = APIRouter(tags=["ui"])
_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    cache_size=0,
)

import json as _json
from pathlib import Path


def _tojson_unicode(value) -> str:
    return _json.dumps(value, indent=2, ensure_ascii=False, default=str)


_env.filters["tojson_unicode"] = _tojson_unicode


def _moscow_time(value, fmt: str = "%d.%m %H:%M") -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        return value
    if not isinstance(value, datetime):
        return str(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone(MOSCOW_TZ)
    return local.strftime(fmt)


_env.filters["moscow_time"] = _moscow_time


def _normalize_artifact_list(
    raw_artifacts: dict[str, str],
    project_id: str,
    remote_job_id: str,
    run_id: str,
    primary_key: str = "",
) -> list[dict]:
    result = []
    for key, val in raw_artifacts.items():
        if not val or not isinstance(val, str):
            val = ""
        server_filename = val.split("/")[-1] if "/" in val else (val if "." in val else "")
        filename = server_filename or resolve_artifact_filename(key, project_id)
        ext = get_artifact_extension(filename)
        previewable = is_previewable(ext)
        preview_kind = get_preview_kind(ext) if previewable else ""
        is_primary = bool(primary_key) and key == primary_key
        result.append({
            "key": key,
            "filename": filename,
            "extension": ext,
            "content_type": PREVIEW_CONTENT_TYPES.get(ext, "application/octet-stream"),
            "previewable": previewable,
            "preview_kind": preview_kind,
            "download_url": f"/runs/{run_id}/artifacts/{key}",
            "preview_url": f"/runs/{run_id}/artifacts/{key}/preview",
            "raw_value": val,
            "is_primary": is_primary,
        })
    result.sort(key=lambda a: (not a["is_primary"], a["filename"]))
    return result


def render(name: str, **context) -> str:
    tpl = _env.get_template(name)
    return tpl.render(**context)


# ── Dashboard (main page) ──


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    projects = load_projects()
    project_cards = []
    all_schedules = schedules_store.list()
    now = datetime.utcnow()
    for p in projects:
        summary = queue_store.get_queue_summary(p.project_id)
        p_schedules = [s for s in all_schedules if s.project_id == p.project_id]
        active_schedules = [s for s in p_schedules if s.enabled]
        runs = [r for r in runs_store.list() if r.project_id == p.project_id]
        last_run = max(runs, key=lambda r: r.created_at, default=None) if runs else None
        stale_days = 999
        if last_run and last_run.created_at:
            stale_days = (now - last_run.created_at).days
        project_cards.append({
            "project": p,
            "queue_summary": summary,
            "schedule_count": len(p_schedules),
            "active_schedule_count": len(active_schedules),
            "last_run": last_run,
            "stale_days": stale_days,
            "primary_artifact": {
                "key": p.primary_artifact.artifact_key,
                "label": p.primary_artifact.label,
            },
        })
    project_cards.sort(key=lambda c: (
        0 if c["queue_summary"].get("failed", 0) > 0 else
        1 if c["stale_days"] > 7 else
        2 if c["queue_summary"].get("queued", 0) > 0 else
        3
    ))
    return HTMLResponse(render(
        "dashboard.html", request=request,
        project_cards=project_cards,
        remote_status_labels=REMOTE_STATUS_LABELS,
    ))


# ── Project pages ──


@router.get("/projects", response_class=HTMLResponse)
async def projects_list_page(request: Request):
    projects = load_projects()
    all_schedules = schedules_store.list()
    all_schedules_by_project = {}
    for s in all_schedules:
        all_schedules_by_project.setdefault(s.project_id, []).append(s)
    queue_summaries = {}
    for p in projects:
        queue_summaries[p.project_id] = queue_store.get_queue_summary(p.project_id)
    return HTMLResponse(render(
        "projects.html", request=request, projects=projects,
        all_schedules_by_project=all_schedules_by_project,
        queue_summaries=queue_summaries,
    ))


@router.get("/projects/new", response_class=HTMLResponse)
async def new_project_page(request: Request):
    platforms = [{"key": p.value, "label": PLATFORM_LABELS[p]} for p in PublishPlatform]
    return HTMLResponse(render(
        "add_project.html", request=request, platforms=platforms,
        all_profiles=profiles_store.list(),
    ))


@router.post("/projects/new", response_class=RedirectResponse)
async def create_project_form(request: Request):
    form = await request.form()
    form_data = dict(form)
    fields = _parse_fields(form_data)
    project = _build_project(form_data, fields)
    save_project(project)
    return RedirectResponse(f"/projects/{project.project_id}", status_code=303)


@router.get("/projects/{project_id}/edit", response_class=HTMLResponse)
async def edit_project_page(request: Request, project_id: str):
    project = get_project(project_id)
    if not project:
        return HTMLResponse("Проект не найден", status_code=404)
    platforms = [{"key": p.value, "label": PLATFORM_LABELS[p]} for p in PublishPlatform]
    return HTMLResponse(render(
        "edit_project.html", request=request, project=project,
        platforms=platforms, all_profiles=profiles_store.list(),
    ))


@router.post("/projects/{project_id}/edit", response_class=RedirectResponse)
async def update_project_form(project_id: str, request: Request):
    project = get_project(project_id)
    if not project:
        return HTMLResponse("Проект не найден", status_code=404)
    form = await request.form()
    form_data = dict(form)
    fields = _parse_fields(form_data)
    updated = _build_project(form_data, fields, existing_id=project_id)
    save_project(updated)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_page(request: Request, project_id: str):
    project = get_project(project_id)
    if not project:
        return HTMLResponse("Проект не найден", status_code=404)
    jobs = get_enabled_jobs(project)
    runs = runs_store.list()
    project_runs = [r for r in runs if r.project_id == project_id][:50]
    schedules = [s for s in schedules_store.list() if s.project_id == project_id]
    profiles = profiles_store.list()
    queue_items = queue_store.list_items(project_id)
    queue_items.sort(key=lambda i: i.position)

    remote_snapshot = await fetch_remote_jobs(project.integration, project_id)
    merged = build_merged_runs(project_id, project_runs, remote_snapshot)
    queue_summary = queue_store.get_queue_summary(project_id)

    content_memory_count = len(content_memory_store.filter(project_id=project_id))

    return HTMLResponse(render(
        "project.html", request=request, project=project, jobs=jobs,
        runs=project_runs, merged_runs=merged, schedules=schedules,
        profiles=profiles, remote_snapshot=remote_snapshot,
        last_sync=remote_snapshot.synced_at if remote_snapshot else None,
        queue_items=queue_items, queue_summary=queue_summary,
        queue_status_labels=QUEUE_STATUS_LABELS,
        content_memory_count=content_memory_count,
    ))


# ── Quick launch / enqueue / draft ──


@router.post("/projects/{project_id}/run", response_class=RedirectResponse)
async def run_project_form(project_id: str, request: Request):
    form = await request.form()
    input_data = dict(form)
    action = input_data.pop("_action", "launch_now")
    title = input_data.pop("_title", "")
    notes = input_data.pop("_notes", "")
    publish_profile_id = input_data.pop("_publish_profile", "")

    clean = {}
    for k, v in input_data.items():
        if not k.startswith("_") and k not in ("field_count",):
            clean[k] = v

    project = get_project(project_id)

    if action == "add_to_queue":
        items = queue_store.list_items(project_id)
        max_pos = max((i.position for i in items), default=-1)
        queue_item = QueueItem(
            project_id=project_id,
            title=title or f"Запуск #{max_pos + 2}",
            payload=clean,
            status=QueueItemStatus.queued,
            position=max_pos + 1,
            source=QueueItemSource.manual,
            notes=notes,
            default_publish_profile_id=publish_profile_id,
        )
        if project:
            queue_item.publish_artifact_key_override = project.primary_artifact.artifact_key
        queue_store.save_item(project_id, queue_item)
        return RedirectResponse(f"/projects/{project_id}", status_code=303)

    elif action == "save_draft":
        items = queue_store.list_items(project_id)
        max_pos = max((i.position for i in items), default=-1)
        queue_item = QueueItem(
            project_id=project_id,
            title=title or f"Черновик #{max_pos + 2}",
            payload=clean,
            status=QueueItemStatus.draft,
            position=max_pos + 1,
            source=QueueItemSource.manual,
            notes=notes,
            default_publish_profile_id=publish_profile_id,
        )
        queue_store.save_item(project_id, queue_item)
        return RedirectResponse(f"/projects/{project_id}", status_code=303)

    else:
        run = await run_project(project_id, clean)
        return RedirectResponse(f"/runs/{run.run_id}", status_code=303)


# ── Queue management routes ──


@router.get("/projects/{project_id}/queue/{queue_item_id}", response_class=HTMLResponse)
async def queue_item_detail_page(request: Request, project_id: str, queue_item_id: str):
    project = get_project(project_id)
    if not project:
        return HTMLResponse("Проект не найден", status_code=404)
    item = queue_store.get_item(project_id, queue_item_id)
    if not item:
        return HTMLResponse("Элемент очереди не найден", status_code=404)
    profiles = profiles_store.list()
    return HTMLResponse(render(
        "queue_item.html", request=request,
        project=project, item=item, profiles=profiles,
        queue_status_labels=QUEUE_STATUS_LABELS,
    ))


@router.post("/projects/{project_id}/queue/{queue_item_id}/edit", response_class=RedirectResponse)
async def queue_item_edit_form(project_id: str, queue_item_id: str, request: Request):
    item = queue_store.get_item(project_id, queue_item_id)
    if not item:
        return HTMLResponse("Item not found", status_code=404)
    form = await request.form()
    form_data = dict(form)
    item.title = form_data.get("title", item.title)
    item.notes = form_data.get("notes", item.notes)
    item.default_publish_profile_id = form_data.get("default_publish_profile_id", "")
    item.publish_artifact_key_override = form_data.get("publish_artifact_key_override", "")

    status_str = form_data.get("status", "")
    if status_str:
        try:
            item.status = QueueItemStatus(status_str)
        except ValueError:
            pass

    payload_raw = form_data.get("payload_json", "{}")
    try:
        item.payload = _json.loads(payload_raw)
    except Exception:
        pass

    item.updated_at = datetime.utcnow()
    queue_store.save_item(project_id, item)
    return RedirectResponse(f"/projects/{project_id}/queue/{queue_item_id}", status_code=303)


@router.post("/projects/{project_id}/queue/{queue_item_id}/launch", response_class=RedirectResponse)
async def launch_queue_item_form(project_id: str, queue_item_id: str):
    item = queue_store.get_item(project_id, queue_item_id)
    if not item:
        return HTMLResponse("Item not found", status_code=404)
    if item.status not in (QueueItemStatus.queued, QueueItemStatus.draft, QueueItemStatus.failed):
        return RedirectResponse(f"/projects/{project_id}", status_code=303)
    try:
        item.status = QueueItemStatus.launching
        item.updated_at = datetime.utcnow()
        queue_store.save_item(project_id, item)
        run = await run_project(project_id, item.payload, queue_item_id=queue_item_id)
        item.status = QueueItemStatus.launched
        item.last_launch_at = datetime.utcnow()
        item.last_run_id = run.run_id
        item.last_remote_job_id = run.remote_job_id
        item.last_error = ""
        item.launch_history.append({
            "run_id": run.run_id,
            "remote_job_id": run.remote_job_id,
            "launched_at": item.last_launch_at.isoformat(),
            "remote_status": run.remote_status.value,
            "trigger": "manual",
        })
        item.updated_at = datetime.utcnow()
        queue_store.save_item(project_id, item)
        return RedirectResponse(f"/runs/{run.run_id}", status_code=303)
    except Exception as e:
        item.status = QueueItemStatus.failed
        item.last_error = str(e)
        item.updated_at = datetime.utcnow()
        queue_store.save_item(project_id, item)
        return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/queue/{queue_item_id}/status", response_class=RedirectResponse)
async def set_queue_item_status_form(project_id: str, queue_item_id: str, request: Request):
    form = await request.form()
    new_status = form.get("status", "")
    item = queue_store.get_item(project_id, queue_item_id)
    if item:
        try:
            item.status = QueueItemStatus(new_status)
            item.updated_at = datetime.utcnow()
            queue_store.save_item(project_id, item)
        except ValueError:
            pass
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/queue/{queue_item_id}/delete", response_class=RedirectResponse)
async def delete_queue_item_form(project_id: str, queue_item_id: str):
    queue_store.delete_item(project_id, queue_item_id)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/queue/{queue_item_id}/duplicate", response_class=RedirectResponse)
async def duplicate_queue_item_form(project_id: str, queue_item_id: str):
    item = queue_store.get_item(project_id, queue_item_id)
    if item:
        import copy, uuid
        new_item = copy.deepcopy(item)
        new_item.queue_item_id = f"q_{uuid.uuid4().hex[:12]}"
        new_item.title = f"{item.title} (копия)" if item.title else "Копия"
        new_item.status = QueueItemStatus.draft
        new_item.created_at = datetime.utcnow()
        new_item.updated_at = datetime.utcnow()
        new_item.last_launch_at = None
        new_item.last_run_id = None
        new_item.last_remote_job_id = None
        new_item.last_error = ""
        new_item.launch_history = []
        items = queue_store.list_items(project_id)
        max_pos = max((i.position for i in items), default=-1)
        new_item.position = max_pos + 1
        queue_store.save_item(project_id, new_item)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/queue/{queue_item_id}/move", response_class=RedirectResponse)
async def move_queue_item_form(project_id: str, queue_item_id: str, request: Request):
    form = await request.form()
    direction = form.get("direction", "up")
    item = queue_store.get_item(project_id, queue_item_id)
    if item:
        items = sorted(queue_store.list_items(project_id), key=lambda i: i.position)
        idx = next((i for i, it in enumerate(items) if it.queue_item_id == queue_item_id), -1)
        if idx >= 0:
            swap_idx = idx - 1 if direction == "up" else idx + 1
            if 0 <= swap_idx < len(items):
                items[idx].position, items[swap_idx].position = items[swap_idx].position, items[idx].position
                queue_store.save_item(project_id, items[idx])
                queue_store.save_item(project_id, items[swap_idx])
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


# ── Launch next ──


@router.post("/projects/{project_id}/launch-next", response_class=RedirectResponse)
async def launch_next_queue_item(project_id: str):
    items = sorted(queue_store.list_items(project_id), key=lambda i: i.position)
    queued = [i for i in items if i.status == QueueItemStatus.queued]
    if not queued:
        return RedirectResponse(f"/projects/{project_id}", status_code=303)
    candidate = queued[0]
    return await launch_queue_item_form(project_id, candidate.queue_item_id)


# ── Run detail page ──


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail_page(request: Request, run_id: str):
    run = runs_store.get(run_id)
    if not run:
        return HTMLResponse("Запуск не найден", status_code=404)
    project = get_project(run.project_id)
    profiles = profiles_store.list()
    publish_reqs = publish_requests_store.filter(run_id=run_id)

    remote_details = None
    primary_artifact = None
    if run.remote_job_id and project and project.integration.api_url:
        remote_details = await fetch_remote_job_details(
            project.integration, run.project_id, run.remote_job_id,
        )
        if remote_details:
            await sync_run_status(run, project.integration)
            run = runs_store.get(run_id)

    normalized_artifacts = []
    primary_artifact_key = project.primary_artifact.artifact_key if project else "final_video"

    if remote_details and remote_details.artifacts:
        normalized_artifacts = _normalize_artifact_list(
            remote_details.artifacts,
            run.project_id,
            run.remote_job_id or "",
            run.run_id,
            primary_key=primary_artifact_key,
        )
        queue_item = None
        if run.queue_item_id:
            queue_item = queue_store.get_item(run.project_id, run.queue_item_id)
        override_key = ""
        if queue_item and queue_item.publish_artifact_key_override:
            override_key = queue_item.publish_artifact_key_override
        pa = resolve_primary_artifact(
            remote_details.artifacts,
            run.project_id,
            primary_artifact_key=primary_artifact_key,
            artifact_key_override=override_key,
        )
        if pa:
            primary_artifact = pa

    return HTMLResponse(render(
        "run.html", request=request, run=run, project=project,
        profiles=profiles, publish_reqs=publish_reqs,
        remote_details=remote_details,
        normalized_artifacts=normalized_artifacts,
        primary_artifact=primary_artifact,
        orch_labels=ORCHESTRATION_LABELS,
        remote_status_labels=REMOTE_STATUS_LABELS,
    ))


async def _fetch_and_serve_artifact(
    run_id: str,
    artifact_key: str,
    disposition: str,
) -> Response:
    run = runs_store.get(run_id)
    if not run:
        return HTMLResponse("Запуск не найден", status_code=404)
    if not run.remote_job_id:
        return HTMLResponse("Нет remote job ID для этого запуска", status_code=400)
    project = get_project(run.project_id)
    if not project or not project.integration.api_url:
        return HTMLResponse("Проект или API URL не настроен", status_code=400)

    from remote_sync import fetch_artifact
    result = await fetch_artifact(
        project.integration, run.remote_job_id, artifact_key,
    )
    if result is None:
        return HTMLResponse("Артефакт не найден или сервер недоступен", status_code=404)

    content, content_type = result
    if disposition == "attachment":
        base_filename = resolve_artifact_filename(artifact_key, run.project_id)
        safe_name = sanitize_filename(f"{run.remote_job_id}_{base_filename}")
        content_disp = f'attachment; filename="{safe_name}"'
    else:
        content_disp = "inline"

    return Response(
        content=content,
        media_type=content_type or "application/octet-stream",
        headers={"Content-Disposition": content_disp},
    )


@router.get("/runs/{run_id}/artifacts/{artifact_key}")
async def download_artifact(run_id: str, artifact_key: str):
    return await _fetch_and_serve_artifact(run_id, artifact_key, "attachment")


@router.get("/runs/{run_id}/artifacts/{artifact_key}/preview")
async def preview_artifact(run_id: str, artifact_key: str):
    return await _fetch_and_serve_artifact(run_id, artifact_key, "inline")


# ── Schedules ──


@router.get("/schedules", response_class=HTMLResponse)
async def schedules_page(request: Request):
    schedules = schedules_store.list()
    projects = {p.project_id: p.display_name for p in load_projects()}
    for s in schedules:
        s._queue_summary = queue_store.get_queue_summary(s.project_id) if s.project_id else {}
    return HTMLResponse(render(
        "schedules.html", request=request,
        schedules=schedules, projects=projects,
    ))


@router.get("/schedules/help", response_class=HTMLResponse)
async def schedules_help_page(request: Request):
    return HTMLResponse(render("schedules_help.html", request=request))


@router.post("/schedules/create", response_class=RedirectResponse)
async def create_schedule_form(
    project_id: str = Form(...),
    cron_expression: str = Form(...),
    title: str = Form(""),
    enabled: str = Form("off"),
):
    is_enabled = enabled in ("on", "true", "1", "yes")

    import re
    cron_pattern = re.compile(r"^(\*|\d+)([-\/,*\d]*) (\*|\d+)([-\/,*\d]*) (\*|\d+)([-\/,*\d]*) (\*|\d+)([-\/,*\d]*) (\*|\d+)([-\/,*\d]*)$")
    if not cron_pattern.match(cron_expression):
        return RedirectResponse(
            f"/projects/{project_id}?schedule_error=Некорректное+cron-выражение:+{cron_expression}",
            status_code=303,
        )

    sched = Schedule(
        project_id=project_id,
        cron_expression=cron_expression,
        title=title,
        enabled=is_enabled,
    )
    try:
        add_schedule(sched)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return RedirectResponse(
            f"/projects/{project_id}?schedule_error=Ошибка+создания+расписания:+{str(e)}",
            status_code=303,
        )
    return RedirectResponse(f"/projects/{project_id}?schedule_ok=Расписание+добавлено", status_code=303)


@router.post("/schedules/{schedule_id}/delete", response_class=RedirectResponse)
async def delete_schedule_form(schedule_id: str):
    sched = schedules_store.get(schedule_id, "schedule_id")
    project_id = sched.project_id if sched else ""
    remove_schedule(schedule_id)
    return RedirectResponse(f"/projects/{project_id}" if project_id else "/schedules", status_code=303)


# ── Publish profiles ──


@router.get("/publish/profiles", response_class=HTMLResponse)
async def publish_profiles_page(request: Request):
    profiles = profiles_store.list()
    profile_usage = {}
    for p in load_projects():
        for binding in p.publish_bindings:
            pid = binding.profile_id
            if pid not in profile_usage:
                profile_usage[pid] = []
            profile_usage[pid].append(p.display_name)
    return HTMLResponse(render(
        "publish_profiles.html", request=request,
        profiles=profiles,
        platforms=PublishPlatform,
        platform_labels=PLATFORM_LABELS,
        platform_short=PLATFORM_SHORT_CAPABLE,
        profile_usage=profile_usage,
    ))


@router.get("/publish/profiles/new", response_class=HTMLResponse)
async def new_publish_profile_page(request: Request):
    platforms = [{"key": p.value, "label": PLATFORM_LABELS[p], "short": PLATFORM_SHORT_CAPABLE[p]} for p in PublishPlatform]
    return HTMLResponse(render(
        "publish_profile_form.html", request=request,
        profile=None, platforms=platforms,
    ))


@router.post("/publish/profiles/new", response_class=RedirectResponse)
async def create_publish_profile_form(request: Request):
    form = await request.form()
    data = dict(form)
    profile = _build_publish_profile(data)
    profiles_store.save(profile, key_attr="profile_id")
    return RedirectResponse("/publish/profiles", status_code=303)


@router.get("/publish/profiles/{profile_id}/edit", response_class=HTMLResponse)
async def edit_publish_profile_page(request: Request, profile_id: str):
    profile = profiles_store.get(profile_id, "profile_id")
    if not profile:
        return HTMLResponse("Профиль не найден", status_code=404)
    platforms = [{"key": p.value, "label": PLATFORM_LABELS[p], "short": PLATFORM_SHORT_CAPABLE[p]} for p in PublishPlatform]
    return HTMLResponse(render(
        "publish_profile_form.html", request=request,
        profile=profile, platforms=platforms,
    ))


@router.post("/publish/profiles/{profile_id}/edit", response_class=RedirectResponse)
async def update_publish_profile_form(profile_id: str, request: Request):
    existing = profiles_store.get(profile_id, "profile_id")
    if not existing:
        return HTMLResponse("Профиль не найден", status_code=404)
    form = await request.form()
    data = dict(form)
    updated = _build_publish_profile(data, existing_id=profile_id)
    profiles_store.save(updated, key_attr="profile_id")
    return RedirectResponse("/publish/profiles", status_code=303)


@router.post("/publish/profiles/{profile_id}/toggle", response_class=RedirectResponse)
async def toggle_publish_profile(profile_id: str):
    profile = profiles_store.get(profile_id, "profile_id")
    if profile:
        profile.enabled = not profile.enabled
        profiles_store.save(profile, key_attr="profile_id")
    return RedirectResponse("/publish/profiles", status_code=303)


@router.post("/publish/profiles/{profile_id}/delete", response_class=RedirectResponse)
async def delete_publish_profile_form(profile_id: str):
    profiles_store.delete(profile_id, "profile_id")
    return RedirectResponse("/publish/profiles", status_code=303)


@router.get("/publish/guide/{platform}", response_class=HTMLResponse)
async def publish_guide_page(request: Request, platform: str):
    try:
        plat = PublishPlatform(platform)
    except ValueError:
        return HTMLResponse("Платформа не найдена", status_code=404)
    return HTMLResponse(render(
        "publish_guide.html", request=request,
        platform=plat,
        platform_label=PLATFORM_LABELS.get(plat, platform),
    ))


_PROJECT_ROOT = Path(__file__).parent


@router.get("/publishing-guide", response_class=HTMLResponse)
async def publishing_access_guide_page(request: Request):
    guide_path = _PROJECT_ROOT / "PUBLISHING_ACCESS_GUIDE.md"
    if not guide_path.exists():
        return HTMLResponse("Файл PUBLISHING_ACCESS_GUIDE.md не найден", status_code=404)
    content = guide_path.read_text(encoding="utf-8")
    html_content = content.replace("\n", "<br>\n").replace("  ", "&nbsp;&nbsp;")
    html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><title>Publishing Access Guide</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #eef0f5; color: #1a1a2e; line-height: 1.7; padding: 2rem; max-width: 800px; margin: 0 auto; }}
  .card {{ background: #fff; border: 1px solid #e2e5ec; border-radius: 16px; padding: 1.5rem 2rem; }}
  a {{ color: #4f46e5; }}
  code {{ background: #f3f4f6; padding: .15rem .4rem; border-radius: 6px; font-size: .85em; }}
  pre {{ background: #f8f9fc; padding: .75rem 1rem; border-radius: 10px; overflow-x: auto; border: 1px solid #e2e5ec; }}
  h1 {{ font-size: 1.3rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 1.5rem; }}
  h3 {{ font-size: .95rem; margin-top: 1.2rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .85rem; }}
  td, th {{ border: 1px solid #e2e5ec; padding: .4rem .6rem; text-align: left; }}
  th {{ background: #f3f4f6; font-weight: 600; }}
</style></head>
<body><div class="card">{html_content}</div></body></html>"""
    return HTMLResponse(html)


@router.post("/publish/request", response_class=RedirectResponse)
async def create_publish_request_form(request: Request):
    form = await request.form()
    data = dict(form)
    req = PublishRequest(
        run_id=data.get("run_id", ""),
        project_id=data.get("project_id", ""),
        profile_id=data.get("profile_id", ""),
        platform=PublishPlatform(data.get("platform", "youtube")),
        title=data.get("title", ""),
        description=data.get("description", ""),
        hashtags=[h.strip() for h in data.get("hashtags", "").split(",") if h.strip()],
        visibility=data.get("visibility", "unlisted"),
        status="pending",
    )
    publish_requests_store.save(req, key_attr="request_id")

    run = runs_store.get(req.run_id)
    if run:
        run.publish_status = "pending"
        run.publish_profile_id = req.profile_id
        runs_store.save(run)

    return RedirectResponse(f"/runs/{req.run_id}", status_code=303)


# ── Helpers ──


def _parse_fields(form_data: dict) -> list[ProjectInputField]:
    fields = []
    count = int(form_data.get("field_count", "0"))
    for i in range(count):
        key = form_data.get(f"field_key_{i}", "").strip()
        label = form_data.get(f"field_label_{i}", "").strip()
        if not key or not label:
            continue
        ftype = form_data.get(f"field_type_{i}", "text")
        required = f"field_req_{i}" in form_data
        options_raw = form_data.get(f"field_options_{i}", "")
        options = [o.strip() for o in options_raw.split(",") if o.strip()] if options_raw else []
        helper = form_data.get(f"field_helper_{i}", "")
        visible = form_data.get(f"field_visible_{i}") == "on"
        can_have_default = form_data.get(f"field_supports_default_{i}") == "on"
        field = ProjectInputField(
            key=key, label=label, type=ftype, required=required,
            options=options, helper_text=helper,
            visible=visible, supports_default=can_have_default,
        )
        default_raw = form_data.get(f"field_default_{i}", "")
        if default_raw:
            field.default = default_raw
        placeholder_raw = form_data.get(f"field_placeholder_{i}", "")
        if placeholder_raw:
            field.placeholder = placeholder_raw
        fields.append(field)
    return fields


def _build_project(form_data: dict, fields: list[ProjectInputField], existing_id: str = "") -> Project:
    pid = existing_id or form_data.get("project_id", "")
    yt = form_data.get("publish_youtube") == "on"
    cron = form_data.get("cron_enabled") == "on"
    enabled = form_data.get("enabled") != "off"

    api_url = form_data.get("api_url", "")
    jobs_list_endpoint = form_data.get("jobs_list_endpoint", "/jobs")
    job_detail_endpoint = form_data.get("job_detail_endpoint", "/jobs/{job_id}")
    job_cancel_endpoint = form_data.get("job_cancel_endpoint", "/jobs/{job_id}/cancel")

    jobs = [
        JobDefinition(
            job_id="run_pipeline",
            title="Запуск пайплайна",
            order=10,
            job_type=JobType.run_pipeline,
            manual_run_allowed=True,
            cron_allowed=cron,
            config={
                "api_url": api_url,
                "run_endpoint": form_data.get("run_endpoint", "/jobs"),
                "status_endpoint": job_detail_endpoint,
            },
        ),
    ]
    if yt:
        jobs.append(
            JobDefinition(
                job_id="publish_youtube",
                title="Публикация в YouTube",
                order=20,
                job_type=JobType.publish_youtube,
                manual_run_allowed=True,
                cron_allowed=False,
            )
        )

    publish_bindings = []
    selected_profiles = form_data.get("publish_profiles", "")
    if selected_profiles:
        profile_ids = [p.strip() for p in selected_profiles.split(",") if p.strip()]
        default_pub = form_data.get("default_publish_profile", "")
        for pid in profile_ids:
            publish_bindings.append(ProjectPublishBinding(
                profile_id=pid,
                enabled=True,
                is_default=(pid == default_pub),
            ))

    auto_sync = form_data.get("auto_sync") == "on"

    primary_artifact_key = form_data.get("primary_artifact_key", "final_video")
    primary_artifact_label = form_data.get("primary_artifact_label", "Финальное видео")

    defaults_input_str = form_data.get("defaults_input_json", "")
    defaults_input = {}
    if defaults_input_str:
        try:
            defaults_input = _json.loads(defaults_input_str)
        except Exception:
            pass

    return Project(
        project_id=pid,
        display_name=form_data.get("display_name", ""),
        description=form_data.get("description", ""),
        enabled=enabled,
        input_fields=fields,
        jobs=jobs,
        publish_targets=(
            [ProjectPublishTarget(target="youtube", label="YouTube", enabled=True)]
            if yt else []
        ),
        integration=ProjectIntegration(
            api_url=api_url,
            integration_type=form_data.get("integration_type", "api"),
            jobs_list_endpoint=jobs_list_endpoint,
            job_detail_endpoint=job_detail_endpoint,
            job_cancel_endpoint=job_cancel_endpoint,
            auto_sync=auto_sync,
        ),
        publish_bindings=publish_bindings,
        config={
            "api_url": api_url,
            "integration_type": form_data.get("integration_type", "api"),
        },
        defaults=ProjectDefaults(input_values=defaults_input),
        primary_artifact={
            "artifact_key": primary_artifact_key,
            "label": primary_artifact_label,
        },
    )


def _build_publish_profile(data: dict, existing_id: str = "") -> PublishProfile:
    profile_id = existing_id or ""
    platform_str = data.get("platform", "youtube")
    try:
        platform = PublishPlatform(platform_str)
    except ValueError:
        platform = PublishPlatform.youtube

    profile = PublishProfile(
        profile_id=profile_id,
        display_name=data.get("display_name", ""),
        platform=platform,
        enabled=data.get("enabled") != "off",
        channel_title=data.get("channel_title", ""),
        channel_id=data.get("channel_id", ""),
        notes=data.get("notes", ""),
    )

    tags_raw = data.get("tags_defaults", "")
    if tags_raw:
        profile.tags_defaults = [t.strip() for t in tags_raw.split(",") if t.strip()]

    if data.get("credentials_json"):
        try:
            profile.credentials = _json.loads(data["credentials_json"])
        except Exception:
            profile.credentials = {"raw": data["credentials_json"]}

    profile.privacy_defaults = {
        "visibility": data.get("visibility", "unlisted"),
    }
    profile.title_defaults = {
        "template": data.get("title_template", ""),
    }
    profile.description_defaults = {
        "template": data.get("description_template", ""),
    }
    profile.shorts_defaults = {
        "enabled": data.get("shorts_enabled") == "on",
        "orientation": data.get("shorts_orientation", "vertical"),
    }

    has_creds = bool(profile.credentials) or bool(data.get("credentials_json"))
    has_basic = bool(profile.channel_title or data.get("channel_title"))
    profile.is_ready = has_creds or has_basic

    return profile
