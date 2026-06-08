from __future__ import annotations

import json
from pathlib import Path
from typing import Generic, TypeVar

from models import Run, Schedule, PublishProfile, PublishRequest, QueueItem

T = TypeVar("T")

DATA_DIR = Path(__file__).parent / "data"
QUEUES_DIR = DATA_DIR / "queues"


class FileStore(Generic[T]):
    def __init__(self, filename: str, model_cls: type[T]):
        self.path = DATA_DIR / filename
        self.model_cls = model_cls
        self.path.parent.mkdir(exist_ok=True)
        if not self.path.exists():
            self._write([])

    def _read(self) -> list[dict]:
        return json.loads(self.path.read_text())

    def _write(self, data: list[dict]):
        self.path.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False))

    def list(self) -> list[T]:
        return [self.model_cls(**d) for d in self._read()]

    def get(self, key: str, attr: str = "run_id") -> T | None:
        for d in self._read():
            if d.get(attr) == key:
                return self.model_cls(**d)
        return None

    def save(self, item: T, key_attr: str = "run_id"):
        items = self._read()
        key = getattr(item, key_attr)
        for i, d in enumerate(items):
            if d.get(key_attr) == key:
                items[i] = item.model_dump(mode="json")
                self._write(items)
                return
        items.append(item.model_dump(mode="json"))
        self._write(items)

    def delete(self, key: str, attr: str = "run_id") -> bool:
        items = self._read()
        new_items = [d for d in items if d.get(attr) != key]
        if len(new_items) == len(items):
            return False
        self._write(new_items)
        return True

    def filter(self, **kwargs) -> list[T]:
        items = self.list()
        result = items
        for attr, value in kwargs.items():
            result = [i for i in result if getattr(i, attr, None) == value]
        return result


class QueueStore:
    """Per-project queue storage in data/queues/<project_id>.json"""

    def __init__(self):
        QUEUES_DIR.mkdir(exist_ok=True)

    def _path(self, project_id: str) -> Path:
        return QUEUES_DIR / f"{project_id}.json"

    def _read_items(self, project_id: str) -> list[dict]:
        path = self._path(project_id)
        if not path.exists():
            return []
        return json.loads(path.read_text())

    def _write_items(self, project_id: str, items: list[dict]):
        self._path(project_id).write_text(
            json.dumps(items, indent=2, default=str, ensure_ascii=False)
        )

    def list_items(self, project_id: str) -> list[QueueItem]:
        return [QueueItem(**d) for d in self._read_items(project_id)]

    def get_item(self, project_id: str, queue_item_id: str) -> QueueItem | None:
        for d in self._read_items(project_id):
            if d.get("queue_item_id") == queue_item_id:
                return QueueItem(**d)
        return None

    def save_item(self, project_id: str, item: QueueItem):
        items = self._read_items(project_id)
        key = item.queue_item_id
        for i, d in enumerate(items):
            if d.get("queue_item_id") == key:
                items[i] = item.model_dump(mode="json")
                self._write_items(project_id, items)
                return
        items.append(item.model_dump(mode="json"))
        self._write_items(project_id, items)

    def delete_item(self, project_id: str, queue_item_id: str) -> bool:
        items = self._read_items(project_id)
        new_items = [d for d in items if d.get("queue_item_id") != queue_item_id]
        if len(new_items) == len(items):
            return False
        self._write_items(project_id, new_items)
        return True

    def get_queue_summary(self, project_id: str) -> dict:
        items = self.list_items(project_id)
        summary = {"total": len(items)}
        for s in ("draft", "queued", "launching", "launched", "failed", "paused", "archived"):
            summary[s] = sum(1 for i in items if i.status.value == s)
        active = [i for i in items if i.status.value in ("queued", "launching")]
        if active:
            summary["next_item_id"] = min(active, key=lambda i: i.position).queue_item_id
        else:
            summary["next_item_id"] = None
        return summary


runs_store = FileStore[Run]("runs.json", Run)
schedules_store = FileStore[Schedule]("schedules.json", Schedule)
profiles_store = FileStore[PublishProfile]("publish_profiles.json", PublishProfile)
publish_requests_store = FileStore[PublishRequest]("publish_requests.json", PublishRequest)
queue_store = QueueStore()
