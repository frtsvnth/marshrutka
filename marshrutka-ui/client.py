"""Клиент к hermes-pipelines API.

Единственный источник данных для UI. Своей базы, своих секретов и своего
состояния у маршрутки больше нет — она только показывает то, что отдаёт API.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

API_URL = os.environ.get("HP_API_URL", "http://127.0.0.1:8010").rstrip("/")
API_TOKEN = os.environ.get("HP_API_TOKEN", "")
TIMEOUT = float(os.environ.get("HP_API_TIMEOUT", "30"))


class ApiError(Exception):
    """Ошибка API, пригодная для показа человеку."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.message = message
        self.status = status


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_TOKEN} if API_TOKEN else {}


async def request(method: str, path: str, **kw: Any) -> dict:
    url = f"{API_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.request(method, url, headers=_headers(), **kw)
    except httpx.RequestError as exc:
        raise ApiError(
            f"hermes-pipelines недоступен по адресу {API_URL}. "
            f"Проверь HP_API_URL и что сервис поднят. ({exc})"
        ) from exc

    if resp.status_code == 401:
        raise ApiError("API отклонил токен. Проверь HP_API_TOKEN.", 401)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text[:300])
        except ValueError:
            detail = resp.text[:300]
        raise ApiError(str(detail), resp.status_code)

    return resp.json()


async def pipelines() -> list[dict]:
    return (await request("GET", "/api/pipelines"))["pipelines"]


async def profiles() -> dict:
    return await request("GET", "/api/profiles")


async def inbox(project: str = "", status: str = "pending") -> list[dict]:
    params = {"status": status}
    if project:
        params["project"] = project
    return (await request("GET", "/api/inbox", params=params))["items"]


async def inbox_add(project: str, payload: dict, title: str = "", note: str = "") -> dict:
    return await request("POST", "/api/inbox", json={
        "project": project, "payload": payload, "title": title, "note": note,
    })


async def inbox_release(inbox_id: int, status: str) -> dict:
    return await request("POST", f"/api/inbox/{inbox_id}/release", json={"status": status})


async def history(project: str = "", limit: int = 30) -> list[dict]:
    params: dict[str, Any] = {"limit": limit}
    if project:
        params["project"] = project
    return (await request("GET", "/api/history", params=params))["items"]


async def history_forget(project: str, key: str) -> dict:
    return await request("DELETE", "/api/history", params={"project": project, "key": key})


async def runs(project: str, status: str = "", limit: int = 20) -> dict:
    params: dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status
    return await request("GET", f"/api/runs/{project}", params=params)


async def run_detail(project: str, job_id: str) -> dict:
    return await request("GET", f"/api/runs/{project}/{job_id}")
