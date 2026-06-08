from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from config import BASE_DIR

logger = logging.getLogger(__name__)

ALLOWED_DIRS = [BASE_DIR]
MAX_FILE_SIZE = 100 * 1024


def _resolve_path(path: str) -> Path | None:
    resolved = (BASE_DIR / path).resolve()
    for allowed in ALLOWED_DIRS:
        if str(resolved).startswith(str(allowed.resolve())):
            return resolved
    return None


def read_project_file(path: str) -> dict:
    try:
        full = _resolve_path(path)
        if not full:
            return {"error": "Путь вне разрешённой директории"}
        if not full.exists():
            return {"error": "Файл не найден"}
        if full.is_dir():
            entries = sorted(
                [str(p.relative_to(BASE_DIR)) for p in full.iterdir() if not p.name.startswith(".")]
            )
            return {
                "path": path,
                "type": "directory",
                "entries": entries,
            }
        size = full.stat().st_size
        if size > MAX_FILE_SIZE:
            return {"error": "Файл слишком большой для чтения"}
        content = full.read_text(encoding="utf-8")
        return {
            "path": path,
            "type": "file",
            "content": content,
            "size": size,
        }
    except Exception as e:
        logger.exception("read_project_file failed: %s", path)
        return {"error": "Ошибка чтения файла"}


def search_project_code(query: str, include: str = "*.py,*.html,*.js,*.css,*.json,*.md") -> dict:
    try:
        extensions = [e.strip() for e in include.split(",")]
        matches = []
        for ext in extensions:
            for f in BASE_DIR.rglob(ext):
                if ".venv" in f.parts or "__pycache__" in f.parts or ".git" in f.parts:
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                    if query.lower() in text.lower():
                        rel = str(f.relative_to(BASE_DIR))
                        lines = text.split("\n")
                        match_lines = [
                            {"line": i + 1, "content": lines[i].strip()}
                            for i in range(len(lines))
                            if query.lower() in lines[i].lower()
                        ]
                        matches.append({
                            "file": rel,
                            "match_count": len(match_lines),
                            "matches": match_lines[:10],
                        })
                except Exception:
                    continue
        matches.sort(key=lambda m: m["match_count"], reverse=True)
        return {"query": query, "file_count": len(matches), "files": matches[:20]}
    except Exception as e:
        logger.exception("search_project_code failed: %s", query)
        return {"error": "Ошибка поиска в проекте"}


def propose_file_patch(path: str, instruction: str) -> dict:
    try:
        full = _resolve_path(path)
        if not full:
            return {"error": "Путь вне разрешённой директории"}
        if not full.exists():
            return {"error": "Файл не найден", "patch_status": "not_found"}
        content = full.read_text(encoding="utf-8")
        return {
            "path": path,
            "current_content": content,
            "instruction": instruction,
            "patch_status": "proposed",
            "note": "Проверь current_content и дай команду apply_file_patch с готовым патчем",
        }
    except Exception as e:
        logger.exception("propose_file_patch failed: %s", path)
        return {"error": "Ошибка подготовки патча"}


def apply_file_patch(path: str, patch: str) -> dict:
    try:
        full = _resolve_path(path)
        if not full:
            return {"error": "Путь вне разрешённой директории"}
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(patch, encoding="utf-8")
        return {
            "path": path,
            "status": "applied",
            "size": len(patch),
        }
    except Exception as e:
        logger.exception("apply_file_patch failed: %s", path)
        return {"error": "Ошибка применения патча"}


def update_config(key: str, value: str) -> dict:
    env_path = BASE_DIR / ".env"
    try:
        lines = []
        found = False
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
        new_lines = []
        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return {"key": key, "status": "updated"}
    except Exception as e:
        logger.exception("update_config failed: %s", key)
        return {"error": "Ошибка обновления конфига"}
