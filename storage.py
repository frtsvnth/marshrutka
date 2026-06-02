from __future__ import annotations

import json
from pathlib import Path
from typing import Generic, TypeVar

from models import Run, Schedule, PublishProfile, PublishRequest

T = TypeVar("T")

DATA_DIR = Path(__file__).parent / "data"


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


runs_store = FileStore[Run]("runs.json", Run)
schedules_store = FileStore[Schedule]("schedules.json", Schedule)
profiles_store = FileStore[PublishProfile]("publish_profiles.json", PublishProfile)
publish_requests_store = FileStore[PublishRequest]("publish_requests.json", PublishRequest)
