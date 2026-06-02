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
    PREVIEW_CONTENT_TYPES,
)
from registry import load_projects, get_project, get_enabled_jobs, save_project
from storage import runs_store, schedules_store, profiles_store, publish_requests_store
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
        })
    result.sort(key=lambda a: a["filename"])
    return result


def render(name: str, **context) -> str:
    tpl = _env.get_template(name)
    return tpl.render(**context)


@router.get("/", response_class=HTMLResponse)
async def projects_page(request: Request):
    projects = load_projects()
    return HTMLResponse(render("projects.html", request=request, projects=projects))


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

    remote_snapshot = await fetch_remote_jobs(project.integration, project_id)
    merged = build_merged_runs(project_id, project_runs, remote_snapshot)

    return HTMLResponse(render(
        "project.html", request=request, project=project, jobs=jobs,
        runs=project_runs, merged_runs=merged, schedules=schedules,
        profiles=profiles, remote_snapshot=remote_snapshot,
        last_sync=remote_snapshot.synced_at if remote_snapshot else None,
    ))


@router.post("/projects/{project_id}/run", response_class=RedirectResponse)
async def run_project_form(project_id: str, request: Request):
    form = await request.form()
    input_data = dict(form)
    run = await run_project(project_id, input_data)
    return RedirectResponse(f"/runs/{run.run_id}", status_code=303)


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail_page(request: Request, run_id: str):
    run = runs_store.get(run_id)
    if not run:
        return HTMLResponse("Запуск не найден", status_code=404)
    project = get_project(run.project_id)
    profiles = profiles_store.list()
    publish_reqs = publish_requests_store.filter(run_id=run_id)

    remote_details = None
    if run.remote_job_id and project and project.integration.api_url:
        remote_details = await fetch_remote_job_details(
            project.integration, run.project_id, run.remote_job_id,
        )
        if remote_details:
            await sync_run_status(run, project.integration)
            run = runs_store.get(run_id)

    normalized_artifacts = []
    if remote_details and remote_details.artifacts:
        normalized_artifacts = _normalize_artifact_list(
            remote_details.artifacts,
            run.project_id,
            run.remote_job_id or "",
            run.run_id,
        )

    return HTMLResponse(render(
        "run.html", request=request, run=run, project=project,
        profiles=profiles, publish_reqs=publish_reqs,
        remote_details=remote_details,
        normalized_artifacts=normalized_artifacts,
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


@router.get("/schedules", response_class=HTMLResponse)
async def schedules_page(request: Request):
    schedules = schedules_store.list()
    projects = {p.project_id: p.display_name for p in load_projects()}
    return HTMLResponse(render("schedules.html", request=request, schedules=schedules, projects=projects))


@router.post("/schedules/create", response_class=RedirectResponse)
async def create_schedule_form(
    project_id: str = Form(...),
    cron_expression: str = Form(...),
    title: str = Form(""),
    enabled: bool = Form(True),
):
    sched = Schedule(project_id=project_id, cron_expression=cron_expression, title=title, enabled=enabled)
    add_schedule(sched)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/schedules/{schedule_id}/delete", response_class=RedirectResponse)
async def delete_schedule_form(schedule_id: str):
    sched = schedules_store.get(schedule_id, "schedule_id")
    project_id = sched.project_id if sched else ""
    remove_schedule(schedule_id)
    return RedirectResponse(f"/projects/{project_id}" if project_id else "/schedules", status_code=303)


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
        fields.append(ProjectInputField(key=key, label=label, type=ftype, required=required, options=options))
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
        import json as _json
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
