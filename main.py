from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import HOST, PORT
from api import router as api_router
from ui import router as ui_router
from scheduler import scheduler, reload_schedules


@asynccontextmanager
async def lifespan(app: FastAPI):
    reload_schedules()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Marshrutka — content workflow runner", version="0.1.0", lifespan=lifespan)

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(api_router)
app.include_router(ui_router)


if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
