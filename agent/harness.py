from __future__ import annotations

import json
import re
from typing import AsyncGenerator

import httpx

from config import ROUTERAI_BASE_URL, ROUTERAI_API_KEY, ROUTERAI_MODEL
from registry import load_projects
from agent.memory import AgentMemory
from agent.tools import TOOLS


async def call_llm(messages: list[dict]) -> str:
    headers = {
        "Authorization": f"Bearer {ROUTERAI_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": ROUTERAI_MODEL,
        "messages": messages,
        "stream": False,
        "max_tokens": 4096,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(60)) as client:
        resp = await client.post(
            f"{ROUTERAI_BASE_URL.rstrip('/')}/chat/completions",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


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


def parse_tool_calls(text: str) -> list[dict]:
    calls = []
    for match in re.finditer(r"<tool_call>(.*?)</tool_call>", text, re.DOTALL):
        try:
            parsed = json.loads(match.group(1).strip())
            if "tool" in parsed and "args" in parsed:
                calls.append(parsed)
        except (json.JSONDecodeError, KeyError):
            pass
    return calls


def strip_tool_calls(text: str) -> str:
    return re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL).strip()


async def run_harness(user_message: str, history: list[dict], memory: AgentMemory) -> AsyncGenerator[str, None]:
    projects = load_projects()
    system_prompt = memory.get_system_prompt(projects)

    messages = [
        {"role": "system", "content": system_prompt},
        *history[-10:],
        {"role": "user", "content": user_message},
    ]

    max_steps = 5
    accumulated_response = ""

    for step in range(max_steps):
        full_response = ""
        in_tool_call = False
        tool_call_buffer = ""

        async for chunk in call_llm_stream(messages):
            full_response += chunk

            if in_tool_call:
                tool_call_buffer += chunk
                if "</tool_call>" in tool_call_buffer:
                    in_tool_call = False
                    tool_call_buffer = ""
                continue

            if "<tool_call" in chunk:
                idx = chunk.index("<tool_call")
                visible = chunk[:idx]
                if visible:
                    yield visible
                in_tool_call = True
                tool_call_buffer = chunk[idx:]
                continue

            yield chunk

        tool_calls = parse_tool_calls(full_response)

        if not tool_calls:
            accumulated_response += full_response
            break

        if step > 0:
            accumulated_response += strip_tool_calls(full_response)

        all_results = []
        for tc in tool_calls:
            tool_name = tc.get("tool", "")
            args = tc.get("args", {})
            if tool_name not in TOOLS:
                result = {"error": f"Unknown tool: {tool_name}"}
            else:
                try:
                    maybe = TOOLS[tool_name](**args)
                    if hasattr(maybe, '__await__'):
                        result = await maybe
                    else:
                        result = maybe
                except Exception as e:
                    result = {"error": str(e)}
            all_results.append(result)

            yield json.dumps({"tool_indicator": f"⚙️ {tool_name}: {_summarize_result(result)}"})

        messages.append({"role": "assistant", "content": full_response})
        messages.append({"role": "tool", "content": json.dumps(all_results, ensure_ascii=False)})

    else:
        accumulated_response += strip_tool_calls(full_response)

    memory.add_to_history("user", user_message)
    memory.add_to_history("assistant", strip_tool_calls(accumulated_response))
    memory.save()


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
    return "выполнено"
