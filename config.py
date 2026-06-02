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
