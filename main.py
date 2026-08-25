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
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import auth
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


# ── Публичные страницы: лендинг, вход, юридические ──────────────────────────
# Не защищены пин-кодом — по ним проходит и живой человек до входа, и ревью
# Google при верификации OAuth-приложения (нужны рабочие Homepage/Privacy/
# Terms ссылки).

@app.get("/")
async def landing(request: Request):
    if auth.is_authed(request):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "landing.html")


@app.get("/privacy")
async def privacy(request: Request):
    return render(request, "privacy.html")


@app.get("/terms")
async def terms(request: Request):
    return render(request, "terms.html")


@app.get("/login")
async def login_page(request: Request):
    if auth.is_authed(request):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "login.html")


@app.post("/login")
async def login_submit(pin: str = Form(...)):
    """JSON, не редирект: страница входа сама шлёт fetch и переходит на
    /dashboard по ok=true — так работает автосабмит по вводу 6-й цифры."""
    if not auth.check_pin(pin):
        return JSONResponse({"ok": False, "error": "Неверный код"}, status_code=401)
    resp = JSONResponse({"ok": True})
    auth.set_session_cookie(resp)
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/", status_code=303)
    auth.clear_session_cookie(resp)
    return resp


# ── Дашборд и остальные страницы: за пин-кодом ───────────────────────────────

CLEANUP_PRESETS = [
    {"mode": "failed", "days": 0, "label": "Ошибки"},
    {"mode": "older_than", "days": 7, "label": "Старше недели"},
    {"mode": "older_than", "days": 30, "label": "Старше месяца"},
]


@app.get("/dashboard")
async def dashboard(request: Request):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect
    try:
        pipelines = await client.pipelines()
        recent = await client.history(limit=12)
    except client.ApiError as exc:
        return render(request, "dashboard.html", pipelines=[], recent=[],
                      system=None, cleanup_presets=CLEANUP_PRESETS, error=exc.message)

    published = sum(1 for r in recent if r["status"] == "published")
    failed = sum(1 for r in recent if r["status"] in ("failed", "publish_failed"))
    pending = sum(p["inbox_pending"] for p in pipelines)
    down = [p["name"] for p in pipelines if not p["alive"]]

    try:
        system = await client.system_info()
    except client.ApiError:
        system = None  # необязательная карточка — не роняем весь дашборд

    return render(request, "dashboard.html", pipelines=pipelines, recent=recent,
                  published=published, failed=failed, pending=pending, down=down,
                  system=system, cleanup_presets=CLEANUP_PRESETS)


@app.post("/cleanup/{project}")
async def cleanup_run(request: Request, project: str, mode: str = Form(...),
                      days: int = Form(0), action: str = Form(...)):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect
    dry_run = action == "preview"
    try:
        result = await client.cleanup(project, mode, days=days, dry_run=dry_run)
    except client.ApiError as exc:
        return RedirectResponse(f"/dashboard?notice={exc.message}", status_code=303)

    name = PROJECT_NAMES.get(project, project)
    if dry_run:
        matched = result.get("matched", 0)
        notice = (f"{name}: под удаление попадёт {matched} job(ов) — "
                  f"нажми «Удалить», чтобы применить") if matched else \
                 f"{name}: удалять нечего"
    else:
        deleted = result.get("deleted", 0)
        freed = result.get("freed_mb")
        extra = f", освобождено {freed} МБ" if freed else ""
        notice = f"{name}: удалено {deleted} job(ов){extra}"
        if result.get("errors"):
            notice += f" (ошибок: {len(result['errors'])})"

    return RedirectResponse(f"/dashboard?notice={notice}", status_code=303)


@app.get("/inbox")
async def inbox_page(request: Request, project: str = ""):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect
    try:
        items = await client.inbox(project, "ready")
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
    redirect = auth.require_auth(request)
    if redirect:
        return redirect
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
async def inbox_release(request: Request, inbox_id: int, status: str = Form("done")):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect
    try:
        await client.inbox_release(inbox_id, status)
        notice = "Возвращено+в+работу" if status == "ready" else "Закрыто"
    except client.ApiError as exc:
        notice = exc.message
    return RedirectResponse(f"/inbox?notice={notice}", status_code=303)


@app.get("/history")
async def history_page(request: Request, project: str = ""):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect
    try:
        items = await client.history(project, limit=50)
    except client.ApiError as exc:
        return render(request, "history.html", items=[], selected=project,
                      error=exc.message)
    return render(request, "history.html", items=items, selected=project)


@app.post("/history/forget")
async def history_forget(request: Request, project: str = Form(...), key: str = Form(...)):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect
    try:
        await client.history_forget(project, key)
        notice = "Материал+снова+доступен"
    except client.ApiError as exc:
        notice = exc.message
    return RedirectResponse(f"/history?notice={notice}", status_code=303)


@app.get("/runs/{project}")
async def runs_page(request: Request, project: str, status: str = ""):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect
    try:
        data = await client.runs(project, status)
    except client.ApiError as exc:
        return render(request, "runs.html", project=project, items=[], total=0,
                      selected_status=status, error=exc.message)
    return render(request, "runs.html", project=project, items=data["items"],
                  total=data["total"], selected_status=status)


@app.get("/runs/{project}/{job_id}")
async def run_page(request: Request, project: str, job_id: str):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect
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
