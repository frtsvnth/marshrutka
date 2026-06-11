from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
YOUTUBE_UPLOAD_BASE = "https://www.googleapis.com/upload/youtube/v3"


def build_auth_url(
    client_id: str,
    redirect_uri: str,
    state: str,
) -> str:
    params = (
        f"client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={'+'.join(SCOPES)}"
        f"&access_type=offline"
        f"&prompt=consent"
        f"&state={state}"
    )
    return f"{AUTH_URL}?{params}"


async def exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


async def get_channels(access_token: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{YOUTUBE_API_BASE}/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])


def get_valid_credentials(credentials: dict[str, Any]) -> dict[str, Any] | None:
    needed = ["client_id", "client_secret", "refresh_token"]
    for key in needed:
        if not credentials.get(key):
            return None

    expires_at = credentials.get("expires_at", 0)
    access_token = credentials.get("access_token", "")

    if access_token and expires_at and time.time() < expires_at - 60:
        return credentials

    return None


async def ensure_valid_credentials(credentials: dict[str, Any]) -> dict[str, Any] | None:
    valid = get_valid_credentials(credentials)
    if valid:
        return valid

    refresh = credentials.get("refresh_token")
    client_id = credentials.get("client_id", "")
    client_secret = credentials.get("client_secret", "")

    if not refresh or not client_id or not client_secret:
        return None

    try:
        token_data = await refresh_access_token(client_id, client_secret, refresh)
        new_access = token_data.get("access_token", "")
        expires_in = token_data.get("expires_in", 3600)
        credentials["access_token"] = new_access
        credentials["expires_at"] = time.time() + expires_in
        return credentials
    except Exception:
        return None


async def upload_video(
    credentials: dict[str, Any],
    video_bytes: bytes,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    privacy_status: str = "unlisted",
) -> dict[str, Any]:
    creds = await ensure_valid_credentials(credentials)
    if not creds:
        raise ValueError("YouTube credentials not available or expired")

    access_token = creds.get("access_token", "")

    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }
    if tags:
        metadata["snippet"]["tags"] = tags[:500]

    async with httpx.AsyncClient() as client:
        init_resp = await client.post(
            f"{YOUTUBE_UPLOAD_BASE}/videos?uploadType=resumable&part=snippet,status",
            json=metadata,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "X-Upload-Content-Type": "video/*",
                "X-Upload-Content-Length": str(len(video_bytes)),
            },
        )
        if init_resp.status_code != 200:
            detail = init_resp.text
            raise ValueError(f"YouTube API upload init failed ({init_resp.status_code}): {detail[:500]}")

        upload_url = init_resp.headers.get("Location", "")
        if not upload_url:
            raise ValueError("No upload URL returned from YouTube API")

        upload_resp = await client.put(
            upload_url,
            content=video_bytes,
            headers={
                "Content-Type": "video/*",
                "Content-Length": str(len(video_bytes)),
            },
        )
        if upload_resp.status_code not in (200, 201):
            detail = upload_resp.text
            raise ValueError(f"YouTube API upload failed ({upload_resp.status_code}): {detail[:500]}")

        return upload_resp.json()
