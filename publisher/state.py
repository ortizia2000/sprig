"""Tracks which posts went out, per platform, and the returned media id (so the
metrics job can look up insights). Shape: {post_id: {platform: media_ref}}.
The GitHub Action commits this file back so reruns never double-post."""
import json
import os

STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "content", "state", "published.json")


def _load():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def is_published(post_id, platform):
    return platform in _load().get(post_id, {})


def mark(post_id, platform, ref=None):
    data = _load()
    data.setdefault(post_id, {})[platform] = ref or True
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def all_refs():
    return _load()
