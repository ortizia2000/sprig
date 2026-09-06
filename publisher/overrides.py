"""Dashboard overrides: content/schedule.json, written by the browser buttons
(reschedule, approve, edit, delete, replace media) through the GitHub API.

posts.yaml stays the source of truth and is never written from the browser —
editing YAML from JavaScript breaks on comments, block scalars and accents. The
override file is a flat map merged on top:

    {"<post id>": {"date": "2026-10-01", "time": "09:00", "review": false,
                   "deleted": true, "caption_en": "...", "caption_es": "...",
                   "hashtags": "...", "media": ["x-1.jpg", "x-2.jpg"]}}

Only the keys below are honoured. Anything else in the file (a typo, an old
key) is ignored rather than trusted — `platforms`, `id` and `tz` can only come
from the YAML.
"""
import json

KEYS = ("date", "time", "review", "deleted", "caption_en", "caption_es", "hashtags", "media")


def load(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def apply(post, overrides):
    """Return a new post dict with that post's overrides merged on top."""
    merged = dict(post)
    ov = overrides.get(post.get("id"), {})
    if not isinstance(ov, dict):
        return merged
    for k in KEYS:
        if k in ov:
            merged[k] = ov[k]
    return merged


def overridden_keys(post_id, overrides):
    ov = overrides.get(post_id, {})
    return [k for k in KEYS if isinstance(ov, dict) and k in ov]
