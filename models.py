from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class OrchestrationStatus(str, Enum):
    draft = "draft"
    submitting = "submitting"
    linked = "linked"
    sync_pending = "sync_pending"
    sync_error = "sync_error"
    detached = "detached"
    cancelled_locally = "cancelled_locally"


ORCHESTRATION_LABELS: dict[OrchestrationStatus, str] = {
    OrchestrationStatus.draft: "Черновик",
    OrchestrationStatus.submitting: "Отправка на сервер",
    OrchestrationStatus.linked: "Связан с сервером",
    OrchestrationStatus.sync_pending: "Ожидает синхронизации",
    OrchestrationStatus.sync_error: "Ошибка синхронизации",
    OrchestrationStatus.detached: "Отвязан от сервера",
    OrchestrationStatus.cancelled_locally: "Отменён локально",
}


class RemoteExecutionStatus(str, Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"
    unknown = "unknown"


REMOTE_STATUS_LABELS: dict[RemoteExecutionStatus, str] = {
    RemoteExecutionStatus.pending: "Ожидает",
    RemoteExecutionStatus.running: "Выполняется",
    RemoteExecutionStatus.success: "Успех",
    RemoteExecutionStatus.failed: "Ошибка",
    RemoteExecutionStatus.cancelled: "Отменён",
    RemoteExecutionStatus.unknown: "Неизвестно",
}


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    skipped = "skipped"
    cancelled = "cancelled"


class JobType(str, Enum):
    run_pipeline = "run_pipeline"
    collect_artifacts = "collect_artifacts"
    publish_youtube = "publish_youtube"
    http_request = "http_request"
    shell_command = "shell_command"


class PublishPlatform(str, Enum):
    youtube = "youtube"
    instagram = "instagram"
    vk_video = "vk_video"
    rutube = "rutube"


PLATFORM_LABELS: dict[PublishPlatform, str] = {
    PublishPlatform.youtube: "YouTube",
    PublishPlatform.instagram: "Instagram",
    PublishPlatform.vk_video: "VK Видео",
    PublishPlatform.rutube: "Rutube",
}

PLATFORM_SHORT_CAPABLE: dict[PublishPlatform, bool] = {
    PublishPlatform.youtube: True,
    PublishPlatform.instagram: True,
    PublishPlatform.vk_video: True,
    PublishPlatform.rutube: True,
}


class SyncSource(str, Enum):
    local = "local"
    remote = "remote"
    merged = "merged"


class ProjectInputField(BaseModel):
    key: str
    label: str
    type: str = "text"
    required: bool = False
    default: Any = None
    placeholder: str = ""
    options: list[str] = []


class ProjectPublishTarget(BaseModel):
    target: str
    label: str
    enabled: bool = True
    config: dict[str, Any] = {}


class JobDefinition(BaseModel):
    job_id: str
    title: str
    order: int
    job_type: JobType
    enabled: bool = True
    manual_run_allowed: bool = True
    cron_allowed: bool = False
    config: dict[str, Any] = {}


class ProjectIntegration(BaseModel):
    api_url: str = ""
    integration_type: str = "api"
    jobs_list_endpoint: str = "/jobs"
    job_detail_endpoint: str = "/jobs/{job_id}"
    job_cancel_endpoint: str = "/jobs/{job_id}/cancel"
    artifacts_endpoint: str = "/jobs/{job_id}/artifacts/{key}"
    auto_sync: bool = True
    last_sync_at: datetime | None = None
    sync_status: str = "never"


class ProjectPublishBinding(BaseModel):
    profile_id: str
    enabled: bool = True
    is_default: bool = False
    platform_defaults: dict[str, Any] = {}


class Project(BaseModel):
    project_id: str
    display_name: str
    description: str = ""
    enabled: bool = True
    input_fields: list[ProjectInputField] = []
    jobs: list[JobDefinition] = []
    publish_targets: list[ProjectPublishTarget] = []
    integration: ProjectIntegration = ProjectIntegration()
    publish_bindings: list[ProjectPublishBinding] = []
    config: dict[str, Any] = {}


class RemoteJobSummary(BaseModel):
    remote_job_id: str
    project_id: str
    status: str
    source: SyncSource = SyncSource.remote
    local_run_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    title: str = ""
    input_summary: str = ""
    has_details: bool = False
    synced_at: datetime | None = None


class RemoteJobDetails(BaseModel):
    remote_job_id: str
    project_id: str
    status: str
    source: SyncSource = SyncSource.remote
    local_run_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    input_data: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []
    progress: dict[str, Any] = {}
    artifacts: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    logs: str = ""
    warnings: list[str] = []
    job_response: dict[str, Any] = {}
    synced_at: datetime = Field(default_factory=datetime.utcnow)


class SyncSnapshot(BaseModel):
    project_id: str
    remote_jobs: list[RemoteJobSummary] = []
    synced_at: datetime = Field(default_factory=datetime.utcnow)
    error: str | None = None


class Run(BaseModel):
    run_id: str = Field(default_factory=lambda: f"launch_{uuid.uuid4().hex[:12]}")
    project_id: str
    orchestration_status: OrchestrationStatus = OrchestrationStatus.draft
    remote_status: RemoteExecutionStatus = RemoteExecutionStatus.unknown
    input: dict[str, Any] = {}
    remote_job_id: str | None = None
    submitted_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    submit_response: dict[str, Any] = {}
    last_sync_at: datetime | None = None
    sync_error: str | None = None
    publish_status: str | None = None
    publish_profile_id: str | None = None


class RemoteJobRef(BaseModel):
    project_id: str
    external_job_id: str
    remote_status: str = "unknown"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    steps: list[dict[str, Any]] = []
    progress: dict[str, Any] = {}
    artifacts: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    logs: str = ""
    warnings: list[str] = []
    job_response: dict[str, Any] = {}
    last_synced_at: datetime | None = None


class Schedule(BaseModel):
    schedule_id: str = Field(default_factory=lambda: f"sched_{uuid.uuid4().hex[:8]}")
    project_id: str
    title: str = ""
    cron_expression: str
    input: dict[str, Any] = {}
    enabled: bool = True
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PublishProfile(BaseModel):
    profile_id: str = Field(default_factory=lambda: f"pub_{uuid.uuid4().hex[:8]}")
    display_name: str
    platform: PublishPlatform
    enabled: bool = True
    credentials: dict[str, Any] = {}
    channel_title: str = ""
    channel_id: str = ""
    privacy_defaults: dict[str, Any] = {}
    title_defaults: dict[str, Any] = {}
    description_defaults: dict[str, Any] = {}
    tags_defaults: list[str] = []
    shorts_defaults: dict[str, Any] = {}
    schedule_defaults: dict[str, Any] = {}
    notes: str = ""
    is_ready: bool = False
    setup_guide_key: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PublishRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: f"pubreq_{uuid.uuid4().hex[:8]}")
    run_id: str
    project_id: str
    profile_id: str
    platform: PublishPlatform
    title: str = ""
    description: str = ""
    hashtags: list[str] = []
    visibility: str = "unlisted"
    status: str = "draft"
    result: dict[str, Any] = {}
    created_at: datetime = Field(default_factory=datetime.utcnow)
    published_at: datetime | None = None


# ── Artifact filename resolution ──

PREVIEW_CONTENT_TYPES: dict[str, str] = {
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "json": "application/json",
    "txt": "text/plain",
    "log": "text/plain",
    "srt": "text/plain",
    "ass": "text/plain",
    "md": "text/markdown",
}

PREVIEW_KIND_MAP: dict[str, str] = {
    "mp4": "video", "webm": "video", "mov": "video",
    "mp3": "audio", "wav": "audio", "m4a": "audio", "ogg": "audio",
    "png": "image", "jpg": "image", "jpeg": "image", "webp": "image", "gif": "image",
    "json": "text", "txt": "text", "log": "text", "srt": "text", "ass": "text", "md": "text",
}

# artifact key → display filename (shared / project-agnostic keys)
ARTIFACT_FILENAME_MAP: dict[str, str] = {
    "audio_mp3": "audio.mp3",
    "subtitles_srt": "subtitles.srt",
    "subtitles_ass": "subtitles.ass",
    "transcript_json": "transcript.json",
    "transcript": "transcript.json",
    "queries_json": "queries.json",
    "media_manifest_json": "media_manifest.json",
    "summary_text": "summary_text.txt",
    "metadata_package": "metadata_package.json",
    "tts_audio": "summary_tts_master.wav",
    "mixed_audio": "mixed_audio.wav",
    "avatar_video": "avatar_render.mp4",
    "telegram_publish": "telegram_publish.json",
    "caption_quality_report": "captions_quality_report.json",
    "preview_video": "summary_video.mp4",
    "subtitled_video": "summary_video_subtitled.mp4",
    "avatar_overlay_video": "summary_video_with_avatar.mp4",
}

# Project-specific overrides for keys that map differently per project
PROJECT_ARTIFACT_OVERRIDES: dict[str, dict[str, str]] = {
    "story-to-video": {
        "final_video": "final.mp4",
    },
    "ezhu-ponyatno": {
        "final_video": "summary_video_final.mp4",
    },
}


def resolve_artifact_filename(artifact_key: str, project_id: str | None = None) -> str:
    overrides = PROJECT_ARTIFACT_OVERRIDES.get(project_id or "", {})
    if artifact_key in overrides:
        return overrides[artifact_key]
    if artifact_key in ARTIFACT_FILENAME_MAP:
        return ARTIFACT_FILENAME_MAP[artifact_key]
    # fallback: use the key itself, replace underscores with spaces as heuristic
    return artifact_key.replace("_", " ") + ".bin"


def get_artifact_extension(filename: str) -> str:
    if "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    return ""


def is_previewable(ext: str) -> bool:
    return ext in PREVIEW_KIND_MAP


def get_preview_kind(ext: str) -> str:
    return PREVIEW_KIND_MAP.get(ext, "")


def sanitize_filename(name: str) -> str:
    safe = name.replace(" ", "_")
    safe = "".join(c for c in safe if c.isalnum() or c in "._-")
    return safe or "artifact"



