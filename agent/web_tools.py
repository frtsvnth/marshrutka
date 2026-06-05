from __future__ import annotations

import logging

import httpx

from config import SERPAPI_API_KEY

logger = logging.getLogger(__name__)

SERPAPI_BASE = "https://serpapi.com/search"
MAX_RESULTS = 10
MIN_RESULTS = 1
SNIPPET_MAX_LENGTH = 300
REQUEST_TIMEOUT = 15


def _clip_results(raw_results: list[dict], max_count: int) -> list[dict]:
    cleaned = []
    for item in raw_results[:max_count]:
        cleaned.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": (item.get("snippet", "") or "")[:SNIPPET_MAX_LENGTH],
        })
    return cleaned


def search_web(query: str, num_results: int = 5) -> dict:
    num_results = max(MIN_RESULTS, min(num_results, MAX_RESULTS))

    if not SERPAPI_API_KEY:
        return {"error": "SerpApi не настроен"}

    try:
        params = {
            "q": query,
            "api_key": SERPAPI_API_KEY,
            "num": num_results,
            "hl": "ru",
        }
        resp = httpx.get(SERPAPI_BASE, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json()
        organic = raw.get("organic_results", [])
        results = _clip_results(organic, num_results)
        return {"query": query, "results": results}
    except Exception as e:
        logger.exception("Web search failed: %s", query)
        return {"error": "Ошибка интернет-поиска"}


def search_youtube(query: str, num_results: int = 5) -> dict:
    num_results = max(MIN_RESULTS, min(num_results, MAX_RESULTS))

    if not SERPAPI_API_KEY:
        return {"error": "SerpApi не настроен"}

    try:
        site_query = f"site:youtube.com/watch {query}"
        params = {
            "q": site_query,
            "api_key": SERPAPI_API_KEY,
            "num": num_results * 2,
            "hl": "ru",
        }
        resp = httpx.get(SERPAPI_BASE, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json()
        organic = raw.get("organic_results", [])

        videos = []
        for item in organic:
            link = item.get("link", "")
            if "youtube.com/watch" in link or "youtu.be/" in link:
                videos.append({
                    "title": item.get("title", ""),
                    "url": link,
                    "snippet": (item.get("snippet", "") or "")[:SNIPPET_MAX_LENGTH],
                })
                if len(videos) >= num_results:
                    break

        return {"query": query, "results": videos}
    except Exception as e:
        logger.exception("YouTube search failed: %s", query)
        return {"error": "Ошибка интернет-поиска"}
