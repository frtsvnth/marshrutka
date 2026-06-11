from __future__ import annotations

import ast
import json
import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from config import BASE_DIR, DATA_DIR
from registry import load_projects, get_project

logger = logging.getLogger(__name__)

CAPABILITIES_CACHE_PATH = DATA_DIR / "agent" / "capabilities.json"

ACTION_INTENTS = {
    "publish": {"publish", "upload", "post", "pub", "публиковать", "опубликуй", "опубликовать", "публикация", "выложить", "залить", "отправить"},
    "enqueue": {"enqueue", "queue", "add_to_queue", "очередь", "в очередь", "добавить в очередь", "поставить"},
    "launch": {"launch", "run", "start", "trigger", "execute", "запустить", "запуск", "запусти", "выполнить", "старт", "trigger"},
    "retry": {"retry", "restart", "rerun", "ретрай", "ретрайни", "повторить", "перезапустить", "заново"},
    "delete": {"delete", "remove", "del", "wipe", "clean", "удалить", "удали", "удаление", "стереть", "очистить"},
    "edit": {"edit", "update", "modify", "change", "patch", "редактировать", "изменить", "обновить", "поправить"},
    "schedule": {"schedule", "cron", "расписание", "каждый день", "каждый час", "автоматически"},
}

OPERATIONAL_INTENTS = {"publish", "enqueue", "launch", "retry", "delete", "schedule", "edit"}


class CapabilityRegistry:
    def __init__(self, root_path: str | Path = ".", cache_path: str | Path = CAPABILITIES_CACHE_PATH):
        self.root_path = Path(root_path) if isinstance(root_path, str) else root_path
        if not self.root_path.is_absolute():
            self.root_path = BASE_DIR / self.root_path
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] | None = None

    def load(self) -> dict:
        if self.cache_path.exists():
            try:
                raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
                self._data = raw
                return raw
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load capability cache: %s", e)
        return {"actions": [], "routes": [], "projects": {}, "ui_actions": [], "discovered_functions": [], "updated_at": ""}

    def save(self, data: dict | None = None):
        if data is not None:
            self._data = data
        if self._data is not None:
            tmp = tempfile.NamedTemporaryFile(
                mode="w",
                dir=str(self.cache_path.parent),
                prefix=f".{self.cache_path.stem}_tmp_",
                suffix=".json",
                delete=False,
                encoding="utf-8",
            )
            try:
                json.dump(self._data, tmp, indent=2, ensure_ascii=False, default=str)
                tmp.close()
                Path(tmp.name).replace(self.cache_path)
            except Exception:
                Path(tmp.name).unlink(missing_ok=True)
                raise

    def refresh(self) -> dict:
        self._data = self.scan_app()
        self.save()
        return self._data

    def get_capabilities(self) -> dict:
        if self._data is None:
            self._data = self.load()
        return self._data

    def get_project_actions(self, project_id: str) -> list[dict]:
        data = self.get_capabilities()
        return [a for a in data.get("actions", []) if a.get("project_id") == project_id]

    def scan_app(self) -> dict:
        actions: list[dict] = []
        known_ids: set[str] = set()

        routes = self._scan_routes()
        projects_data = self._scan_project_configs()
        ui_actions = self._scan_ui_actions()
        discovered_functions = self._scan_code_patterns()

        for route in routes:
            action = self._route_to_action(route)
            if action and action["action_id"] not in known_ids:
                known_ids.add(action["action_id"])
                actions.append(action)

        for pid, pdata in projects_data.items():
            for binding in pdata.get("publish_bindings", []):
                aid = f"{pid}.publish_{binding.get('target', binding.get('profile_id', 'unknown'))}"
                if aid not in known_ids:
                    known_ids.add(aid)
                    actions.append({
                        "action_id": aid,
                        "project_id": pid,
                        "label": f"Publish via {binding.get('label', binding.get('profile_id', 'unknown'))}",
                        "kind": "config_binding",
                        "path": f"/api/projects/{pid}/publish",
                        "source": "project_config",
                        "requires_confirmation": True,
                        "params_schema": {"run_id": "string"},
                    })

        for ua in ui_actions:
            aid = ua.get("action_id", "")
            if aid and aid not in known_ids:
                known_ids.add(aid)
                actions.append(ua)

        for func in discovered_functions:
            aid = func.get("action_id", "")
            if aid and aid not in known_ids:
                known_ids.add(aid)
                actions.append(func)

        return {
            "actions": actions,
            "routes": routes,
            "projects": projects_data,
            "ui_actions": ui_actions,
            "discovered_functions": discovered_functions,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _scan_routes(self) -> list[dict]:
        routes = []
        api_path = BASE_DIR / "api.py"
        if not api_path.exists():
            return routes
        try:
            tree = ast.parse(api_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    route_info = self._parse_decorator(decorator, node)
                    if route_info:
                        routes.append(route_info)
        except SyntaxError as e:
            logger.warning("Failed to parse api.py: %s", e)
        return routes

    def _parse_decorator(self, decorator: ast.expr, func: ast.FunctionDef) -> dict | None:
        decorator_str = ast.unparse(decorator) if hasattr(ast, "unparse") else None
        if decorator_str is None:
            return None

        method_match = re.match(r"router\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]", decorator_str)
        if not method_match:
            return None

        method = method_match.group(1).upper()
        path = method_match.group(2)

        if path.startswith("/agent"):
            return None

        project_match = re.search(r"\{project_id\}", path)
        project_relation = bool(project_match)

        return {
            "method": method,
            "path": path,
            "handler": func.name,
            "module": "api.py",
            "project_relation": project_relation,
            "docstring": ast.get_docstring(func) or "",
        }

    def _scan_project_configs(self) -> dict[str, Any]:
        projects_data = {}
        try:
            projects = load_projects()
            for p in projects:
                pdict = p.model_dump(mode="json") if hasattr(p, "model_dump") else {}
                info = {
                    "project_id": p.project_id,
                    "display_name": p.display_name,
                    "enabled": p.enabled,
                    "integration": {
                        "api_url": p.integration.api_url if p.integration else "",
                    },
                    "publish_bindings": [
                        {
                            "profile_id": b.profile_id,
                            "enabled": b.enabled,
                            "is_default": b.is_default,
                        }
                        for b in (p.publish_bindings if hasattr(p, "publish_bindings") else [])
                    ],
                    "publish_targets": [
                        {"target": t.target, "label": t.label, "enabled": t.enabled}
                        for t in (p.publish_targets if hasattr(p, "publish_targets") else [])
                    ],
                    "has_schedules": bool(pdict.get("schedules", [])),
                    "input_field_count": len(p.input_fields) if hasattr(p, "input_fields") else 0,
                    "defaults": {
                        "publish_profile_id": p.defaults.publish_profile_id if hasattr(p, "defaults") and p.defaults else "",
                    },
                    "primary_artifact": {
                        "artifact_key": p.primary_artifact.artifact_key if hasattr(p, "primary_artifact") and p.primary_artifact else "final_video",
                    },
                }
                projects_data[p.project_id] = info
        except Exception as e:
            logger.warning("Failed to scan project configs: %s", e)
        return projects_data

    def _scan_ui_actions(self) -> list[dict]:
        actions = []
        templates_dir = BASE_DIR / "templates"
        if not templates_dir.exists():
            return actions
        for tpl in sorted(templates_dir.glob("*.html")):
            try:
                content = tpl.read_text(encoding="utf-8")
                actions.extend(self._extract_ui_actions(content, tpl.name))
            except Exception as e:
                logger.debug("Failed to scan template %s: %s", tpl.name, e)
        return actions

    def _extract_ui_actions(self, html: str, filename: str) -> list[dict]:
        actions = []
        form_pattern = re.compile(
            r'<form\s[^>]*action=["\'](/[^"\']+)["\'].*?method=["\'](POST|GET|post|get)["\']',
            re.DOTALL,
        )
        for match in form_pattern.finditer(html):
            path = match.group(1)
            method = match.group(2).upper()
            project_match = re.search(r"\{project\.project_id\}", html)
            route_pattern = re.sub(r"\{\{[^}]+\}\}", "{param}", path)
            action_id = f"ui.{filename}.{method.lower()}.{route_pattern.replace('/', '_')}"
            actions.append({
                "action_id": action_id,
                "kind": "ui_form",
                "method": method,
                "path_template": route_pattern,
                "source": f"template:{filename}",
                "requires_confirmation": True,
                "params_schema": {},
            })

        button_pattern = re.compile(
            r'action=["\'](/[^"\']+)["\'].*?method=["\'](POST|GET)["\']',
            re.DOTALL,
        )
        seen_paths = set()
        for match in button_pattern.finditer(html):
            path = match.group(1)
            if path in seen_paths:
                continue
            seen_paths.add(path)
            project_match = re.search(r"\{project\.project_id\}", html)
            aid = f"ui.{filename}.form.{path.replace('/', '_')}"
            actions.append({
                "action_id": aid,
                "kind": "ui_form",
                "method": "POST",
                "path_template": path,
                "source": f"template:{filename}",
                "requires_confirmation": True,
                "params_schema": {},
            })
        return actions

    def _scan_code_patterns(self) -> list[dict]:
        patterns = {
            "publish": re.compile(r"(?:async\s+)?def\s+(publish_?\w*|enqueue_?\w*)", re.IGNORECASE),
            "launch": re.compile(r"(?:async\s+)?def\s+(launch_?\w*|run_?\w*)", re.IGNORECASE),
            "queue": re.compile(r"(?:async\s+)?def\s+(enqueue_?\w*|queue_?\w*)", re.IGNORECASE),
            "retry": re.compile(r"(?:async\s+)?def\s+(retry_?\w*|restart_?\w*)", re.IGNORECASE),
            "delete": re.compile(r"(?:async\s+)?def\s+(delete_?\w*|remove_?\w*)", re.IGNORECASE),
        }

        functions = []
        seen = set()
        for f in BASE_DIR.rglob("*.py"):
            if ".venv" in f.parts or "__pycache__" in f.parts or ".git" in f.parts:
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        fname = node.name
                        for intent, pattern in patterns.items():
                            if pattern.match(fname) and fname not in seen:
                                seen.add(fname)
                                doc = ast.get_docstring(node) or ""
                                functions.append({
                                    "action_id": f"code.{fname}",
                                    "label": fname.replace("_", " ").title(),
                                    "kind": "internal_function",
                                    "source": f"file:{str(f.relative_to(BASE_DIR))}",
                                    "requires_confirmation": True,
                                    "params_schema": {},
                                    "intent": intent,
                                })
            except SyntaxError:
                continue
        return functions

    def _route_to_action(self, route: dict) -> dict | None:
        path = route["path"]
        method = route["method"]
        handler = route["handler"]
        project_relation = route.get("project_relation", False)

        for intent, keywords in ACTION_INTENTS.items():
            if any(kw in handler.lower() for kw in keywords) or any(kw in path.lower() for kw in keywords):
                project_id = None
                if project_relation:
                    project_id_placeholder = re.search(r"\{project_id\}", path)
                    if project_id_placeholder:
                        project_id = "{project_id}"

                aid_base = path.replace("/", ".").strip(".").lower()
                return {
                    "action_id": f"route.{aid_base}.{method.lower()}",
                    "project_id": project_id,
                    "label": handler.replace("_", " ").title(),
                    "kind": "endpoint",
                    "method": method,
                    "path": path,
                    "source": "route",
                    "requires_confirmation": method in ("POST", "PUT", "DELETE", "PATCH"),
                    "params_schema": {},
                    "intent": intent,
                }

        if method in ("POST", "PUT", "DELETE", "PATCH"):
            aid_base = path.replace("/", ".").strip(".").lower()
            return {
                "action_id": f"route.{aid_base}.{method.lower()}",
                "project_id": re.search(r"\{project_id\}", path).group() if re.search(r"\{project_id\}", path) else None,
                "label": handler.replace("_", " ").title(),
                "kind": "endpoint",
                "method": method,
                "path": path,
                "source": "route",
                "requires_confirmation": True,
                "params_schema": {},
            }

        return None

    def match_intent(self, user_message: str) -> str | None:
        msg_lower = user_message.lower()
        for intent, keywords in ACTION_INTENTS.items():
            if any(kw in msg_lower for kw in keywords):
                return intent
        return None

    def is_operational_request(self, user_message: str) -> bool:
        intent = self.match_intent(user_message)
        return intent in OPERATIONAL_INTENTS if intent else False

    def detect_publish_intent(self, user_message: str) -> bool:
        msg_lower = user_message.lower()
        publish_kw = ACTION_INTENTS.get("publish", set())
        return any(kw in msg_lower for kw in publish_kw)

    def find_actions_for_intent(self, intent: str, project_id: str | None = None) -> list[dict]:
        data = self.get_capabilities()
        actions = data.get("actions", [])
        keywords = ACTION_INTENTS.get(intent, set())
        matched = []
        for a in actions:
            a_intent = a.get("intent", "")
            a_label = a.get("label", "").lower()
            a_aid = a.get("action_id", "").lower()
            if a_intent == intent:
                matched.append(a)
            elif any(kw in a_label for kw in keywords):
                matched.append(a)
            elif any(kw in a_aid for kw in keywords):
                matched.append(a)
        if project_id:
            matched = [a for a in matched if a.get("project_id") == project_id or a.get("project_id") is None or "{project_id}" in str(a.get("path", ""))]
        return matched


_capability_registry: CapabilityRegistry | None = None


def get_registry() -> CapabilityRegistry:
    global _capability_registry
    if _capability_registry is None:
        _capability_registry = CapabilityRegistry()
        _capability_registry.load()
    return _capability_registry


class OperationalIntentAnalyzer:
    def __init__(self, registry: CapabilityRegistry | None = None):
        self.registry = registry or get_registry()

    def analyze(self, user_message: str) -> dict:
        intent = self.registry.match_intent(user_message)
        if not intent:
            return {"is_operational": False}

        project_id = self._extract_project_id(user_message)
        if self.registry._data is None:
            self.registry.refresh()
        actions = self.registry.find_actions_for_intent(intent, project_id)
        all_actions = self.registry.get_capabilities().get("actions", [])

        return {
            "is_operational": True,
            "detected_intent": intent,
            "detected_project_id": project_id,
            "matched_actions": actions,
            "total_discovered_actions": len(all_actions),
            "has_executable_action": any(a.get("kind") in ("endpoint", "internal_function") for a in actions),
        }

    def _extract_project_id(self, message: str) -> str | None:
        projects = load_projects()
        msg_lower = message.lower()
        for p in projects:
            if p.project_id.lower() in msg_lower or p.display_name.lower() in msg_lower:
                return p.project_id
        match = re.search(r"(?:проект[аеу]?\s+)?['\"`]?([a-z][a-z0-9_-]+)['\"`]?", msg_lower)
        if match:
            candidate = match.group(1)
            for p in projects:
                if p.project_id == candidate:
                    return candidate
        return None


async def discover_project_capabilities(project_id: str | None = None) -> dict:
    registry = get_registry()
    registry.refresh()
    data = registry.get_capabilities()

    if project_id:
        actions = registry.get_project_actions(project_id)
        project_info = data.get("projects", {}).get(project_id, {})
        routes = [r for r in data.get("routes", []) if project_id in r.get("path", "") or r.get("project_relation")]
        return {
            "project_id": project_id,
            "project_info": project_info,
            "actions": actions,
            "routes": routes,
            "total_actions": len(actions),
            "updated_at": data.get("updated_at", ""),
        }

    return {
        "all_actions": data.get("actions", []),
        "routes": data.get("routes", []),
        "projects": data.get("projects", {}),
        "ui_actions": data.get("ui_actions", []),
        "total_actions": len(data.get("actions", [])),
        "updated_at": data.get("updated_at", ""),
    }


async def list_project_actions(project_id: str) -> dict:
    registry = get_registry()
    data = registry.get_capabilities()
    actions = registry.get_project_actions(project_id)
    project_info = data.get("projects", {}).get(project_id, {})

    by_intent: dict[str, list[dict]] = {}
    for a in actions:
        intent = a.get("intent", "other")
        by_intent.setdefault(intent, []).append(a)

    return {
        "project_id": project_id,
        "project_info": project_info,
        "actions": actions,
        "by_intent": by_intent,
        "count": len(actions),
    }


async def invoke_project_action(action_id: str, params: dict | None = None) -> dict:
    registry = get_registry()
    actions = registry.get_capabilities().get("actions", [])
    action = next((a for a in actions if a["action_id"] == action_id), None)
    if not action:
        return {"error": f"Action not found: {action_id}"}

    kind = action.get("kind", "")
    method = action.get("method", "POST")
    path = action.get("path", "")

    if "{project_id}" in path:
        if not params or "project_id" not in params:
            return {
                "error": "Action requires project_id parameter",
                "action": action,
                "resolved": False,
                "manual_path": path.replace("{project_id}", "<project_id>"),
            }
        path = path.replace("{project_id}", params["project_id"])

    base_url = f"http://localhost:9090"

    if kind == "endpoint":
        url = f"{base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
                if method == "GET":
                    resp = await client.get(url, params=params.get("query_params", {}))
                elif method == "DELETE":
                    resp = await client.delete(url)
                else:
                    resp = await client.post(url, json=params.get("body", {}))
                resp.raise_for_status()
                return {
                    "status": "invoked",
                    "action_id": action_id,
                    "method": method,
                    "path": path,
                    "status_code": resp.status_code,
                    "response": resp.json() if resp.text else {},
                }
        except httpx.HTTPStatusError as e:
            return {
                "status": "http_error",
                "action_id": action_id,
                "method": method,
                "path": path,
                "status_code": e.response.status_code,
                "error": str(e),
            }
        except Exception as e:
            return {
                "status": "error",
                "action_id": action_id,
                "error": str(e),
                "action": action,
            }

    if kind in ("ui_form", "config_binding"):
        url = f"{base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
                resp = await client.post(url, data=params.get("form_data", {}))
                resp.raise_for_status()
                return {
                    "status": "invoked",
                    "action_id": action_id,
                    "method": "POST",
                    "path": path,
                    "status_code": resp.status_code,
                    "response": resp.text[:2000],
                }
        except Exception as e:
            return {
                "status": "error",
                "action_id": action_id,
                "error": str(e),
                "action": action,
            }

    if kind == "internal_function":
        return {
            "status": "unsafe_invoke",
            "action_id": action_id,
            "message": "Internal function cannot be safely invoked automatically. A file patch wrapper or manual call is needed.",
            "action": action,
        }

    return {
        "status": "unknown_kind",
        "action_id": action_id,
        "kind": kind,
        "action": action,
    }


async def refresh_capability_registry() -> dict:
    registry = get_registry()
    data = registry.refresh()
    return {
        "status": "refreshed",
        "action_count": len(data.get("actions", [])),
        "route_count": len(data.get("routes", [])),
        "project_count": len(data.get("projects", {})),
        "ui_action_count": len(data.get("ui_actions", [])),
        "updated_at": data.get("updated_at", ""),
    }


async def fetch_json_url(url: str) -> dict:
    if not url or not url.startswith(("http://", "https://")):
        return {"error": "Invalid URL"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20), follow_redirects=True) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "").lower()
            if "json" in content_type or url.endswith(".json"):
                return {
                    "url": url,
                    "status_code": resp.status_code,
                    "data": resp.json(),
                    "content_type": content_type,
                }
            return {
                "url": url,
                "status_code": resp.status_code,
                "error": f"URL returned {content_type}, not JSON",
            }
    except httpx.TimeoutException:
        return {"error": "Timeout fetching URL"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e}"}
    except json.JSONDecodeError:
        return {"error": "Response is not valid JSON"}
    except Exception as e:
        return {"error": str(e)}
