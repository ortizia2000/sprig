"""TikTok publishing via the Content Posting API (video only).

Two modes, picked by TIKTOK_MODE:

  - inbox (default): uploads the video to Nelly's TikTok inbox as a DRAFT.
    She gets an in-app notification and taps publish (caption is added there —
    the inbox flow does not carry captions). Works without TikTok's app audit.
  - direct: posts immediately with the caption. Until the app passes TikTok's
    audit, direct posts are forced to SELF_ONLY visibility, so keep this off
    until the audit is approved.

Auth: TikTok access tokens live 24h, so every run mints a fresh one from the
365-day refresh token (TIKTOK_REFRESH_TOKEN + client key/secret). If TikTok
rotates the refresh token in that response, we print a loud warning with the
new value's tail so the GitHub secret can be updated before the old one dies."""
import sys

import requests

from . import config

API = "https://open.tiktokapis.com/v2"
_access_token_cache = None


def _raise_api_error(r, what):
    """TikTok wraps errors as {"error": {"code": ..., "message": ...}}; surface them."""
    try:
        err = r.json().get("error", {})
    except ValueError:
        r.raise_for_status()
        return
    if err.get("code") in (None, "ok"):
        r.raise_for_status()
        return
    raise RuntimeError(
        f"TikTok {what} failed: {err.get('code')}: {err.get('message')}"
        f" (log_id: {r.json().get('error', {}).get('log_id', '?')})"
    )


def _access_token():
    """24h token from the long-lived refresh token; cached for the run."""
    global _access_token_cache
    if _access_token_cache:
        return _access_token_cache
    if not (config.TIKTOK_CLIENT_KEY and config.TIKTOK_CLIENT_SECRET and config.TIKTOK_REFRESH_TOKEN):
        raise RuntimeError(
            "TikTok not configured (need TIKTOK_CLIENT_KEY + TIKTOK_CLIENT_SECRET + TIKTOK_REFRESH_TOKEN)"
        )
    r = requests.post(
        f"{API}/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": config.TIKTOK_CLIENT_KEY,
            "client_secret": config.TIKTOK_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": config.TIKTOK_REFRESH_TOKEN,
        },
        timeout=30,
    )
    body = r.json() if r.ok else {}
    if not r.ok or "access_token" not in body:
        _raise_api_error(r, "token refresh")
        raise RuntimeError(f"TikTok token refresh failed: {r.status_code} {r.text[:200]}")
    rotated = body.get("refresh_token", "")
    if rotated and rotated != config.TIKTOK_REFRESH_TOKEN:
        print(
            "WARNING tiktok: refresh token was ROTATED — update the TIKTOK_REFRESH_TOKEN "
            f"repo secret (new one ends ...{rotated[-8:]}) before the old one expires",
            file=sys.stderr,
        )
    _access_token_cache = body["access_token"]
    return _access_token_cache


def _headers():
    return {"Authorization": f"Bearer {_access_token()}",
            "Content-Type": "application/json; charset=UTF-8"}


def _init_upload(video_size, caption):
    src = {"source": "FILE_UPLOAD", "video_size": video_size,
           "chunk_size": video_size, "total_chunk_count": 1}
    if config.TIKTOK_MODE == "direct":
        path, body = "post/publish/video/init/", {
            "post_info": {"title": caption[:2200],
                          "privacy_level": config.TIKTOK_PRIVACY},
            "source_info": src,
        }
    else:
        path, body = "post/publish/inbox/video/init/", {"source_info": src}
    r = requests.post(f"{API}/{path}", headers=_headers(), json=body, timeout=60)
    if not r.ok:
        _raise_api_error(r, "upload init")
    data = r.json()["data"]
    return data["publish_id"], data["upload_url"]


def publish_video(video_url, caption):
    """Upload one video (single chunk, fine below TikTok's 64MB chunk ceiling)."""
    _access_token()  # validate config + auth BEFORE downloading the video
    binary = requests.get(video_url, timeout=120).content
    size = len(binary)
    if not size:
        raise RuntimeError(f"TikTok upload: fetched 0 bytes from {video_url}")
    publish_id, upload_url = _init_upload(size, caption)
    put = requests.put(
        upload_url,
        data=binary,
        headers={"Content-Type": "video/mp4",
                 "Content-Range": f"bytes 0-{size - 1}/{size}"},
        timeout=300,
    )
    if not put.ok:
        _raise_api_error(put, "video upload")
    return publish_id
