from __future__ import annotations

from fastapi import APIRouter, HTTPException

from models import Run, Schedule, Project, PublishProfile, PublishRequest, PublishPlatform
from registry import load_projects, get_project, save_project
from scheduler import add_schedule, remove_schedule, reload_schedules
from storage import runs_store, schedules_store, profiles_store, publish_requests_store
from runner import run_project
from remote_sync import fetch_remote_jobs, fetch_remote_job_details

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
    p = get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    run = await run_project(project_id, input_data)
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


from agent.router import router as agent_router
router.include_router(agent_router)
