"""Merges posts.yaml + published state + metrics into docs/data.json, which the
static dashboard reads. Run after publish/metrics, and committed so the UI is fresh."""
import datetime
import json
import os

import yaml

ROOT = os.path.dirname(os.path.dirname(__file__))
MEDIA_BASE = os.environ.get("MEDIA_BASE_URL") or \
    "https://raw.githubusercontent.com/ortizia2000/sprig/main/content/media"


def _read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def run():
    posts = yaml.safe_load(open(os.path.join(ROOT, "content", "posts.yaml")))["posts"]
    state = _read_json(os.path.join(ROOT, "content", "state", "published.json"), {})
    metrics = _read_json(os.path.join(ROOT, "content", "metrics.json"), {})
    sched = _read_json(os.path.join(ROOT, "content", "schedule.json"), {})

    rows = []
    for p in posts:
        pid = p["id"]
        ov = sched.get(pid, {})
        rows.append({
            "id": pid,
            "date": str(ov.get("date", p.get("date"))),
            "time": ov.get("time", p.get("time")),
            "tz": p.get("tz", "America/New_York"),
            "type": p.get("type"),
            "platforms": p.get("platforms", []),
            "thumb": ("media/" + os.path.basename(p.get("cover") or p["media"][0])) if (p.get("cover") or p.get("media")) else None,
            "media": [f"{MEDIA_BASE.rstrip('/')}/{os.path.basename(m)}" for m in p.get("media", [])],
            "caption_en": p.get("caption_en", "").strip(),
            "caption_es": p.get("caption_es", "").strip(),
            "hashtags": p.get("hashtags", "").strip(),
            "published": list(state.get(pid, {}).keys()),
            "metrics": metrics.get(pid, {}),
        })

    data = {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes"), "posts": rows}
    out = os.path.join(ROOT, "docs", "data.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"wrote {out} ({len(rows)} posts)")


if __name__ == "__main__":
    run()
