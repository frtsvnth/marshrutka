from __future__ import annotations

from fastapi import APIRouter, HTTPException

from models import (
    Run, Schedule, Project, PublishProfile, PublishRequest, PublishPlatform,
    QueueItem, QueueItemStatus,
)
from registry import load_projects, get_project, save_project
from scheduler import add_schedule, remove_schedule, reload_schedules
from storage import runs_store, schedules_store, profiles_store, publish_requests_store, queue_store
from runner import run_project
from remote_sync import fetch_remote_jobs, fetch_remote_job_details, fetch_artifact

import youtube_adapter
from config import YOUTUBE_REDIRECT_URI

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/projects")
async def list_projects():
    return load_projects()


@router.get("/projects/{project_id}")
async def get_project_detail(project_id: str):
    p = get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


@router.post("/projects")
async def create_project(project: Project):
    save_project(project)
    return project


@router.put("/projects/{project_id}")
async def update_project(project_id: str, project: Project):
    existing = get_project(project_id)
    if not existing:
        raise HTTPException(404, "Project not found")
    save_project(project)
    return project


@router.post("/runs")
async def create_run(body: dict):
    project_id = body.get("project_id", "")
    input_data = body.get("input", {})
    queue_item_id = body.get("queue_item_id", "")
    p = get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    run = await run_project(project_id, input_data, queue_item_id=queue_item_id)
    return run


@router.get("/runs")
async def list_runs():
    return runs_store.list()


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = runs_store.get(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.get("/runs/{run_id}/logs")
async def get_run_logs(run_id: str):
    run = runs_store.get(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return {
        "run_id": run_id,
        "orchestration_status": run.orchestration_status.value,
        "remote_status": run.remote_status.value,
        "remote_job_id": run.remote_job_id,
        "sync_error": run.sync_error,
    }


# ── Queue API ──


@router.get("/projects/{project_id}/queue")
async def get_project_queue(project_id: str):
    p = get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return queue_store.list_items(project_id)


@router.get("/projects/{project_id}/queue/summary")
async def get_project_queue_summary(project_id: str):
    p = get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return queue_store.get_queue_summary(project_id)


@router.get("/projects/{project_id}/queue/{queue_item_id}")
async def get_queue_item(project_id: str, queue_item_id: str):
    p = get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    item = queue_store.get_item(project_id, queue_item_id)
    if not item:
        raise HTTPException(404, "Queue item not found")
    return item


@router.post("/projects/{project_id}/queue")
async def create_queue_item(project_id: str, item: QueueItem):
    p = get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    item.project_id = project_id
    items = queue_store.list_items(project_id)
    max_pos = max((i.position for i in items), default=-1)
    if item.position <= 0:
        item.position = max_pos + 1
    queue_store.save_item(project_id, item)
    return item


@router.put("/projects/{project_id}/queue/{queue_item_id}")
async def update_queue_item(project_id: str, queue_item_id: str, item: QueueItem):
    existing = queue_store.get_item(project_id, queue_item_id)
    if not existing:
        raise HTTPException(404, "Queue item not found")
    item.queue_item_id = queue_item_id
    item.project_id = project_id
    item.updated_at = __import__("datetime").datetime.utcnow()
    queue_store.save_item(project_id, item)
    return item


@router.post("/projects/{project_id}/queue/{queue_item_id}/status")
async def set_queue_item_status(project_id: str, queue_item_id: str, body: dict):
    status_str = body.get("status", "")
    try:
        new_status = QueueItemStatus(status_str)
    except ValueError:
        raise HTTPException(400, f"Invalid status: {status_str}")
    item = queue_store.get_item(project_id, queue_item_id)
    if not item:
        raise HTTPException(404, "Queue item not found")
    item.status = new_status
    item.updated_at = __import__("datetime").datetime.utcnow()
    queue_store.save_item(project_id, item)
    return item


@router.post("/projects/{project_id}/queue/{queue_item_id}/launch")
async def launch_queue_item(project_id: str, queue_item_id: str):
    item = queue_store.get_item(project_id, queue_item_id)
    if not item:
        raise HTTPException(404, "Queue item not found")
    p = get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    if item.status not in (QueueItemStatus.queued, QueueItemStatus.draft, QueueItemStatus.failed):
        raise HTTPException(400, f"Cannot launch item in status: {item.status.value}")
    try:
        item.status = QueueItemStatus.launching
        item.updated_at = __import__("datetime").datetime.utcnow()
        queue_store.save_item(project_id, item)
        run = await run_project(project_id, item.payload, queue_item_id=queue_item_id)
        item.status = QueueItemStatus.launched
        item.last_launch_at = __import__("datetime").datetime.utcnow()
        item.last_run_id = run.run_id
        item.last_remote_job_id = run.remote_job_id
        item.last_error = ""
        item.launch_history.append({
            "run_id": run.run_id,
            "remote_job_id": run.remote_job_id,
            "launched_at": item.last_launch_at.isoformat() if item.last_launch_at else "",
            "remote_status": run.remote_status.value,
        })
        item.updated_at = __import__("datetime").datetime.utcnow()
        queue_store.save_item(project_id, item)
        return {"ok": True, "run_id": run.run_id}
    except Exception as e:
        item.status = QueueItemStatus.failed
        item.last_error = str(e)
        item.updated_at = __import__("datetime").datetime.utcnow()
        queue_store.save_item(project_id, item)
        raise HTTPException(500, f"Launch failed: {e}")


@router.delete("/projects/{project_id}/queue/{queue_item_id}")
async def delete_queue_item(project_id: str, queue_item_id: str):
    ok = queue_store.delete_item(project_id, queue_item_id)
    if not ok:
        raise HTTPException(404, "Queue item not found")
    return {"ok": True}


@router.post("/projects/{project_id}/queue/{queue_item_id}/move")
async def move_queue_item(project_id: str, queue_item_id: str, body: dict):
    direction = body.get("direction", "up")
    item = queue_store.get_item(project_id, queue_item_id)
    if not item:
        raise HTTPException(404, "Queue item not found")
    items = sorted(queue_store.list_items(project_id), key=lambda i: i.position)
    idx = next((i for i, it in enumerate(items) if it.queue_item_id == queue_item_id), -1)
    if idx < 0:
        raise HTTPException(404, "Queue item not found in list")
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(items):
        raise HTTPException(400, "Cannot move further")
    items[idx].position, items[swap_idx].position = items[swap_idx].position, items[idx].position
    queue_store.save_item(project_id, items[idx])
    queue_store.save_item(project_id, items[swap_idx])
    return {"ok": True}


@router.post("/projects/{project_id}/queue/{queue_item_id}/duplicate")
async def duplicate_queue_item(project_id: str, queue_item_id: str):
    item = queue_store.get_item(project_id, queue_item_id)
    if not item:
        raise HTTPException(404, "Queue item not found")
    import copy, uuid
    new_item = copy.deepcopy(item)
    new_item.queue_item_id = f"q_{uuid.uuid4().hex[:12]}"
    new_item.title = f"{item.title} (копия)" if item.title else "Копия"
    new_item.status = QueueItemStatus.draft
    new_item.created_at = __import__("datetime").datetime.utcnow()
    new_item.updated_at = __import__("datetime").datetime.utcnow()
    new_item.last_launch_at = None
    new_item.last_run_id = None
    new_item.last_remote_job_id = None
    new_item.last_error = ""
    new_item.launch_history = []
    items = queue_store.list_items(project_id)
    max_pos = max((i.position for i in items), default=-1)
    new_item.position = max_pos + 1
    queue_store.save_item(project_id, new_item)
    return new_item


# ── Schedules API ──


@router.get("/schedules")
async def list_schedules():
    return schedules_store.list()


@router.post("/schedules")
async def create_schedule(schedule: Schedule):
    p = get_project(schedule.project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    add_schedule(schedule)
    return schedule


@router.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, schedule: Schedule):
    existing = schedules_store.get(schedule_id, "schedule_id")
    if not existing:
        raise HTTPException(404, "Schedule not found")
    from scheduler import remove_schedule
    remove_schedule(schedule_id)
    add_schedule(schedule)
    return schedule


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str):
    remove_schedule(schedule_id)
    return {"ok": True}


@router.post("/schedules/reload")
async def reload_all_schedules():
    reload_schedules()
    return {"ok": True}


@router.get("/health")
async def health():
    return {"status": "ok", "app": "marshrutka"}


@router.get("/projects/{project_id}/remote-jobs")
async def get_remote_jobs(project_id: str):
    p = get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    snapshot = await fetch_remote_jobs(p.integration, project_id)
    return snapshot


@router.get("/projects/{project_id}/remote-jobs/{remote_job_id}")
async def get_remote_job_detail(project_id: str, remote_job_id: str):
    p = get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    details = await fetch_remote_job_details(p.integration, project_id, remote_job_id)
    if not details:
        raise HTTPException(404, "Remote job not found or sync failed")
    return details


@router.get("/publish/profiles")
async def list_publish_profiles():
    return profiles_store.list()


@router.get("/publish/profiles/{profile_id}")
async def get_publish_profile(profile_id: str):
    profile = profiles_store.get(profile_id, "profile_id")
    if not profile:
        raise HTTPException(404, "Publish profile not found")
    return profile


@router.post("/publish/profiles")
async def create_publish_profile(profile: PublishProfile):
    profiles_store.save(profile, key_attr="profile_id")
    return profile


@router.put("/publish/profiles/{profile_id}")
async def update_publish_profile(profile_id: str, profile: PublishProfile):
    existing = profiles_store.get(profile_id, "profile_id")
    if not existing:
        raise HTTPException(404, "Publish profile not found")
    profiles_store.save(profile, key_attr="profile_id")
    return profile


@router.delete("/publish/profiles/{profile_id}")
async def delete_publish_profile(profile_id: str):
    ok = profiles_store.delete(profile_id, "profile_id")
    if not ok:
        raise HTTPException(404, "Publish profile not found")
    return {"ok": True}


@router.get("/publish/requests")
async def list_publish_requests(run_id: str | None = None):
    if run_id:
        return publish_requests_store.filter(run_id=run_id)
    return publish_requests_store.list()


@router.post("/publish/requests")
async def create_publish_request(req: PublishRequest):
    publish_requests_store.save(req, key_attr="request_id")
    return req


# ── YouTube OAuth API ──


@router.get("/publish/youtube/oauth/url")
async def get_youtube_oauth_url(profile_id: str):
    profile = profiles_store.get(profile_id, "profile_id")
    if not profile:
        raise HTTPException(404, "Profile not found")
    if profile.platform != PublishPlatform.youtube:
        raise HTTPException(400, "Profile is not a YouTube profile")

    client_id = profile.credentials.get("client_id", "")
    if not client_id:
        raise HTTPException(400, "No client_id in profile credentials")

    auth_url = youtube_adapter.build_auth_url(
        client_id=client_id,
        redirect_uri=YOUTUBE_REDIRECT_URI,
        state=profile_id,
    )
    return {"url": auth_url}


@router.get("/publish/youtube/oauth/channels")
async def get_youtube_pending_channels(profile_id: str):
    profile = profiles_store.get(profile_id, "profile_id")
    if not profile:
        raise HTTPException(404, "Profile not found")
    channels = profile.credentials.get("_pending_channels", [])
    if not channels:
        raise HTTPException(400, "No pending channels. Re-authorize the profile.")
    return {"channels": channels, "profile_id": profile_id}


@router.post("/publish/youtube/oauth/select-channel")
async def select_youtube_channel(body: dict):
    profile_id = body.get("profile_id", "")
    channel_id = body.get("channel_id", "")
    channel_title = body.get("channel_title", "")

    profile = profiles_store.get(profile_id, "profile_id")
    if not profile:
        raise HTTPException(404, "Profile not found")

    profile.channel_id = channel_id
    profile.channel_title = channel_title
    profile.credentials["selected_channel_id"] = channel_id
    profile.credentials["selected_channel_title"] = channel_title
    profile.credentials.pop("_pending_channels", None)
    profile.is_ready = True
    profiles_store.save(profile, key_attr="profile_id")
    return {"ok": True, "profile_id": profile_id}


# ── Publish execute ──


@router.post("/publish/execute/{request_id}")
async def execute_publish_request(request_id: str):
    req = publish_requests_store.get(request_id, "request_id")
    if not req:
        raise HTTPException(404, "Publish request not found")

    if req.status not in ("pending", "draft"):
        raise HTTPException(400, f"Cannot execute request in status: {req.status}")

    profile = profiles_store.get(req.profile_id, "profile_id")
    if not profile:
        raise HTTPException(404, "Publish profile not found")
    if not profile.is_ready:
        raise HTTPException(400, "Publish profile is not ready")

    run = runs_store.get(req.run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    project = get_project(run.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    if not run.remote_job_id:
        raise HTTPException(400, "Run has no remote job id")

    try:
        artifact_key = project.primary_artifact.artifact_key
        if req.title:
            title = req.title
        else:
            title = run.input.get("title", run.input.get("news_text", "Video"))[:100]

        description = req.description or ""
        tags = req.hashtags or []

        privacy = profile.privacy_defaults.get("visibility", req.visibility or "unlisted")

        result = await fetch_artifact(
            project.integration, run.remote_job_id, artifact_key,
        )
        if result is None:
            raise ValueError(f"Artifact '{artifact_key}' not found")

        video_bytes, _ = result

        if profile.platform == PublishPlatform.youtube:
            upload_result = await youtube_adapter.upload_video(
                credentials=profile.credentials,
                video_bytes=video_bytes,
                title=title,
                description=description,
                tags=tags,
                privacy_status=privacy,
            )
            req.status = "published"
            req.result = {
                "video_id": upload_result.get("id", ""),
                "channel_id": profile.channel_id,
                "platform": "youtube",
            }
        else:
            req.status = "failed"
            req.result = {"error": f"Unsupported platform: {profile.platform.value}"}

    except Exception as e:
        req.status = "failed"
        req.result = {"error": str(e)}

    req.published_at = __import__("datetime").datetime.utcnow()
    publish_requests_store.save(req, key_attr="request_id")

    run.publish_status = req.status
    run.publish_profile_id = req.profile_id
    runs_store.save(run)

    return req


from agent.router import router as agent_router
router.include_router(agent_router)
