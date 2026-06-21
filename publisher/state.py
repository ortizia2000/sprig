"""Tracks which posts have already gone out, per platform, so reruns never double-post.
The GitHub Action commits this file back to the repo after each run."""
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
    return platform in _load().get(post_id, [])


def mark(post_id, platform):
    data = _load()
    data.setdefault(post_id, [])
    if platform not in data[post_id]:
        data[post_id].append(platform)
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
