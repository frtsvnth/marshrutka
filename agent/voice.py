from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import httpx

from config import STT_HTTP_URL

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30


async def transcribe_audio(audio_data: bytes, filename: str = "recording.webm") -> dict:
    if not STT_HTTP_URL:
        return {"error": "STT endpoint not configured"}
    try:
        suffix = Path(filename).suffix if filename else ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name

        async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT)) as client:
            with open(tmp_path, "rb") as f:
                files = {"file": (filename, f, "audio/webm")}
                resp = await client.post(STT_HTTP_URL, files=files)
            Path(tmp_path).unlink(missing_ok=True)
            resp.raise_for_status()
            result = resp.json()
            text = result.get("text", "").strip()
            if not text:
                return {"error": "Речь не распознана"}
            return {
                "text": text,
                "language": result.get("language", "ru"),
                "duration": result.get("duration", 0),
            }
    except httpx.TimeoutException:
        return {"error": "Таймаут распознавания речи"}
    except Exception as e:
        logger.exception("Transcription failed")
        return {"error": "Ошибка распознавания речи"}
