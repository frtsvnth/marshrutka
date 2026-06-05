from __future__ import annotations

import re

VALID_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")


def validate_session_id(sid: str) -> str:
    if not sid or not isinstance(sid, str):
        raise ValueError("session_id is required")
    if not VALID_SESSION_ID_RE.match(sid):
        raise ValueError(
            "session_id must be 8-64 characters, alphanumeric, hyphens, and underscores only"
        )
    return sid


def is_valid_session_id(sid: str) -> bool:
    try:
        validate_session_id(sid)
        return True
    except ValueError:
        return False
