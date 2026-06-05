from pathlib import Path

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
AGENT_MEMORY_FILE = DATA_DIR / "agent_memory.json"
