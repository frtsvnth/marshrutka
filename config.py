from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
PROJECTS_DIR = BASE_DIR / "projects"
TEMPLATES_DIR = BASE_DIR / "templates"

DATA_DIR.mkdir(exist_ok=True)
PROJECTS_DIR.mkdir(exist_ok=True)

HOST = "0.0.0.0"
PORT = 9090
STORY_TO_VIDEO_URL = "http://141.136.44.9:8001"
EZHU_PONYATNO_URL = "http://141.136.44.9:8000"

import os
from dotenv import load_dotenv
load_dotenv()

ROUTERAI_BASE_URL = os.environ.get("ROUTERAI_BASE_URL", "https://routerai.ru/api/v1")
ROUTERAI_API_KEY = os.environ.get("ROUTERAI_API_KEY", "")
ROUTERAI_MODEL = os.environ.get("ROUTERAI_MODEL", "deepseek/deepseek-v4-flash")
SERPAPI_API_KEY = os.environ.get("SERPAPI_API_KEY", "")
STT_HTTP_URL = os.environ.get("STT_HTTP_URL", "http://141.136.44.9:9000/transcribe")


def moscow_time(dt: datetime | None, fmt: str = "%d.%m %H:%M") -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("Europe/Moscow")).strftime(fmt)
