from __future__ import annotations

import logging
import re

import httpx

from agent.web_tools import search_web

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20
MAX_TEXT_LENGTH = 8000


def fetch_url(url: str) -> dict:
    if not url or not url.startswith(("http://", "https://")):
        return {"error": "Некорректный URL"}
    try:
        resp = httpx.get(url, timeout=REQUEST_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            return {"error": "URL не является HTML-страницей"}
        text = resp.text
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = text[:MAX_TEXT_LENGTH]
        return {
            "url": url,
            "content": text,
            "content_length": len(text),
            "status_code": resp.status_code,
        }
    except httpx.TimeoutException:
        return {"error": "Таймаут при загрузке страницы"}
    except Exception as e:
        logger.exception("fetch_url failed: %s", url)
        return {"error": "Ошибка загрузки страницы"}


def research_topic(query: str, num_queries: int = 3) -> dict:
    try:
        results = search_web(query, num_results=num_queries)
        if "error" in results:
            return results
        urls = [r["url"] for r in results.get("results", [])[:3]]
        pages = []
        for url in urls:
            page = fetch_url(url)
            if "error" not in page:
                pages.append({
                    "url": url,
                    "content": page.get("content", "")[:2000],
                })
        return {
            "query": query,
            "search_results": results.get("results", []),
            "page_contents": pages,
        }
    except Exception as e:
        logger.exception("research_topic failed: %s", query)
        return {"error": "Ошибка исследования темы"}
