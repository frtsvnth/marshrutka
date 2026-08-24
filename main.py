"""Маршрутка — окно в конвейеры.

Управление живёт в Hermes. Здесь только пять страниц: посмотреть, что
происходит, положить материал в инбокс и разобраться, почему упал прогон.

Ни базы, ни секретов, ни планировщика: всё через youtube-pipelines API.

Запуск:
    uvicorn main:app --host 0.0.0.0 --port 8100
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import client

BASE_DIR = Path(__file__).parent

app = FastAPI(title="Marshrutka", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

PROJECT_NAMES = {
    "ezhu-ponyatno": "Ежу понятно",
    "story-to-video": "Истории в видео",
    "zad-pegasa": "Зад Пегаса",
}

# Какое поле payload заполняет форма инбокса и как его подписать.
INPUT_FIELDS = {
    "ezhu-ponyatno": {"key": "url", "label": "Ссылка на YouTube-видео",
                      "multiline": False,
                      "placeholder": "https://www.youtube.com/watch?v=..."},
    "story-to-video": {"key": "news_text", "label": "Текст новости",
                       "multiline": True,
                       "placeholder": "Закадровый текст, 110–170 слов..."},
    "zad-pegasa": {"key": "text", "label": "Текст истории",
                   "multiline": True,
                   "placeholder": "Текст истории, 130–200 слов..."},
}


def render(request: Request, name: str, **ctx):
    ctx.setdefault("project_names", PROJECT_NAMES)
    ctx.setdefault("error", None)
    ctx.setdefault("notice", request.query_params.get("notice"))
    try:
        # Сигнатура Starlette >= 0.29
        return templates.TemplateResponse(request, name, ctx)
    except TypeError:
        # Старая сигнатура: request передаётся внутри контекста
        return templates.TemplateResponse(name, {"request": request, **ctx})


@app.get("/health")
async def health() -> dict:
    """Свой health не зависит от API: контейнер должен считаться живым,
    даже когда конвейеры лежат."""
    return {"status": "ok"}


@app.get("/")
async def dashboard(request: Request):
    try:
        pipelines = await client.pipelines()
        recent = await client.history(limit=12)
    except client.ApiError as exc:
        return render(request, "dashboard.html", pipelines=[], recent=[],
                      error=exc.message)

    published = sum(1 for r in recent if r["status"] == "published")
    failed = sum(1 for r in recent if r["status"] in ("failed", "publish_failed"))
    pending = sum(p["inbox_pending"] for p in pipelines)
    down = [p["name"] for p in pipelines if not p["alive"]]

    return render(request, "dashboard.html", pipelines=pipelines, recent=recent,
                  published=published, failed=failed, pending=pending, down=down)


@app.get("/inbox")
async def inbox_page(request: Request, project: str = ""):
    try:
        items = await client.inbox(project, "pending")
        taken = await client.inbox(project, "taken")
        pipelines = await client.pipelines()
    except client.ApiError as exc:
        return render(request, "inbox.html", items=[], taken=[], pipelines=[],
                      selected=project, fields=INPUT_FIELDS, error=exc.message)

    return render(request, "inbox.html", items=items, taken=taken,
                  pipelines=pipelines, selected=project, fields=INPUT_FIELDS)


@app.post("/inbox/add")
async def inbox_add(request: Request, project: str = Form(...),
                    value: str = Form(...), title: str = Form("")):
    field = INPUT_FIELDS.get(project)
    if not field:
        return RedirectResponse("/inbox?notice=Неизвестный+проект", status_code=303)

    value = value.strip()
    if not value:
        return RedirectResponse("/inbox?notice=Пустое+поле", status_code=303)

    payload = {field["key"]: value}
    if project == "zad-pegasa":
        payload["tts_mode"] = "elevenlabs"

    try:
        await client.inbox_add(project, payload, title=title.strip() or value[:80])
    except client.ApiError as exc:
        return RedirectResponse(f"/inbox?notice={exc.message}", status_code=303)

    return RedirectResponse("/inbox?notice=Добавлено+в+инбокс", status_code=303)


@app.post("/inbox/{inbox_id}/release")
async def inbox_release(inbox_id: int, status: str = Form("done")):
    try:
        await client.inbox_release(inbox_id, status)
        notice = "Возвращено+в+работу" if status == "pending" else "Закрыто"
    except client.ApiError as exc:
        notice = exc.message
    return RedirectResponse(f"/inbox?notice={notice}", status_code=303)


@app.get("/history")
async def history_page(request: Request, project: str = ""):
    try:
        items = await client.history(project, limit=50)
    except client.ApiError as exc:
        return render(request, "history.html", items=[], selected=project,
                      error=exc.message)
    return render(request, "history.html", items=items, selected=project)


@app.post("/history/forget")
async def history_forget(project: str = Form(...), key: str = Form(...)):
    try:
        await client.history_forget(project, key)
        notice = "Материал+снова+доступен"
    except client.ApiError as exc:
        notice = exc.message
    return RedirectResponse(f"/history?notice={notice}", status_code=303)


@app.get("/runs/{project}")
async def runs_page(request: Request, project: str, status: str = ""):
    try:
        data = await client.runs(project, status)
    except client.ApiError as exc:
        return render(request, "runs.html", project=project, items=[], total=0,
                      selected_status=status, error=exc.message)
    return render(request, "runs.html", project=project, items=data["items"],
                  total=data["total"], selected_status=status)


@app.get("/runs/{project}/{job_id}")
async def run_page(request: Request, project: str, job_id: str):
    try:
        data = await client.run_detail(project, job_id)
    except client.ApiError as exc:
        return render(request, "run.html", project=project, job_id=job_id,
                      job=None, error=exc.message)
    return render(request, "run.html", project=project, job_id=job_id,
                  job=data["job"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("UI_HOST", "0.0.0.0"),
                port=int(os.environ.get("UI_PORT", "8100")))
