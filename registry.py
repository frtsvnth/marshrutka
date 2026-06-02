from __future__ import annotations

import json
from pathlib import Path

from models import Project, ProjectInputField, JobDefinition, ProjectPublishTarget, JobType

PROJECTS_DIR = Path(__file__).parent / "projects"


def load_projects() -> list[Project]:
    projects = []
    for path in sorted(PROJECTS_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        projects.append(Project(**data))
    return projects


def get_project(project_id: str) -> Project | None:
    for p in load_projects():
        if p.project_id == project_id:
            return p
    return None


def get_enabled_projects() -> list[Project]:
    return [p for p in load_projects() if p.enabled]


def get_enabled_jobs(project: Project) -> list[JobDefinition]:
    return sorted([j for j in project.jobs if j.enabled], key=lambda j: j.order)


def save_project(project: Project):
    path = PROJECTS_DIR / f"{project.project_id}.json"
    path.write_text(json.dumps(project.model_dump(mode="json"), indent=2, ensure_ascii=False))
