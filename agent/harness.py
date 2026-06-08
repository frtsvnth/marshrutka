from __future__ import annotations

import json
import logging
import time
from typing import AsyncGenerator

import httpx

from config import ROUTERAI_BASE_URL, ROUTERAI_API_KEY, ROUTERAI_MODEL
from registry import load_projects
from agent.memory import MemoryManager
from agent.models import (
    SSEEvent,
    build_openai_tools,
    execute_tool,
)

logger = logging.getLogger(__name__)

TOOL_DEFS = build_openai_tools()


async def call_llm(
    messages: list[dict],
    tools: list[dict] | None = None,
    stream: bool = False,
    max_tokens: int = 4096,
) -> dict:
    headers = {
        "Authorization": f"Bearer {ROUTERAI_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": ROUTERAI_MODEL,
        "messages": messages,
        "stream": stream,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools

    async with httpx.AsyncClient(timeout=httpx.Timeout(120)) as client:
        resp = await client.post(
            f"{ROUTERAI_BASE_URL.rstrip('/')}/chat/completions",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        msg = choice.get("message", {})
        return msg


async def call_llm_stream(messages: list[dict]) -> AsyncGenerator[str, None]:
    headers = {
        "Authorization": f"Bearer {ROUTERAI_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": ROUTERAI_MODEL,
        "messages": messages,
        "stream": True,
        "max_tokens": 4096,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(120)) as client:
        resp = await client.post(
            f"{ROUTERAI_BASE_URL.rstrip('/')}/chat/completions",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()

        buffer = ""
        async for chunk in resp.aiter_bytes():
            buffer += chunk.decode("utf-8")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                if line == "data: [DONE]":
                    return
                if line.startswith("data: "):
                    payload = line[6:]
                    try:
                        data = json.loads(payload)
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        pass


async def run_harness(
    user_message: str,
    memory_manager: MemoryManager,
    session_id: str,
    max_steps: int = 5,
) -> AsyncGenerator[SSEEvent, None]:
    projects = load_projects()
    system_prompt = memory_manager.build_system_prompt(projects)
    _, session_memory = memory_manager.get_session(session_id)

    recent = session_memory.get_recent()
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        *recent,
        {"role": "user", "content": user_message},
    ]

    yield SSEEvent(type="message_start")

    final_content = ""

    for step in range(max_steps):
        msg = await call_llm(messages, tools=TOOL_DEFS, stream=False)

        tool_calls = msg.get("tool_calls", [])
        content = msg.get("content") or ""

        if not tool_calls:
            final_content = content or ""
            break

        if tool_calls:
            messages.append({"role": "assistant", "content": content or "", "tool_calls": tool_calls})

        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                args = {}

            yield SSEEvent(type="tool_start", data={
                "tool_name": tool_name,
                "arguments": args,
            })

            t0 = time.monotonic()
            result = await execute_tool(tool_name, args, memory_manager)
            duration_ms = int((time.monotonic() - t0) * 1000)
            result_str = json.dumps(result, ensure_ascii=False)

            yield SSEEvent(type="tool_result", data={
                "tool_name": tool_name,
                "result_summary": _summarize_result(result),
                "duration_ms": duration_ms,
            })

            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result_str})
    else:
        if not final_content:
            final_content = "(агент не смог сформировать ответ)"

    if final_content:
        yield SSEEvent(type="message_done", data={"content": final_content})

    session_memory.add_message("user", user_message)
    session_memory.add_message("assistant", final_content)


def _summarize_result(result: dict) -> str:
    if "error" in result:
        return f"ошибка: {result['error']}"
    if "word_count" in result:
        return f"{result['word_count']} слов, {result['char_count']} символов"
    if "projects" in result:
        return f"{result['count']} проектов"
    if "runs" in result:
        return f"{result['count']} запусков"
    if "run_id" in result:
        return f"запуск {result['run_id']} — {result.get('status', '?')}"
    if "schedule_id" in result:
        return f"расписание {result['schedule_id']}"
    if "schedules" in result:
        return f"{result['count']} расписаний"
    if "results" in result:
        count = len(result["results"])
        q = result.get("query", "")
        return f"найдено {count} результатов по запросу «{q}»"
    if "content" in result and "url" in result:
        return f"загружено {result.get('content_length', 0)} символов с {result.get('url', '')}"
    if "page_contents" in result:
        return f"исследовано {len(result['page_contents'])} страниц по теме «{result.get('query', '')}»"
    if "issues" in result or "recommendations" in result:
        issues = len(result.get("issues", []))
        recs = len(result.get("recommendations", []))
        return f"{issues} проблем, {recs} рекомендаций"
    if "suggestions" in result:
        return f"{len(result['suggestions'])} предложений"
    if "task_id" in result:
        return f"задача {result['task_id']} создана"
    if "tasks" in result:
        return f"{result['task_count']} задач"
    if "file_count" in result:
        return f"найдено в {result['file_count']} файлах"
    if "status" in result and result.get("status") == "remembered":
        return f"запомнено: {result.get('key', '')}"
    if "status" in result and result.get("status") == "applied":
        return f"патч применён к {result.get('path', '')}"
    if "status" in result and result.get("status") == "updated":
        return f"конфиг {result.get('key', '')} обновлён"
    if "entries" in result:
        return f"список файлов/директорий"
    return "выполнено"
