"""Entry point. Reads content/posts.yaml, publishes any post that is due and
not yet sent, and records what went out (with the returned media id for metrics).

    python -m publisher.publish
"""
import datetime
import json
import os
import sys

import yaml

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from . import config, facebook, instagram, linkedin, state

ROOT = os.path.dirname(os.path.dirname(__file__))
POSTS_FILE = os.path.join(ROOT, "content", "posts.yaml")
SCHEDULE_FILE = os.path.join(ROOT, "content", "schedule.json")


def _overrides():
    """Per-post date/time overrides set from the dashboard (drag-drop / edit)."""
    try:
        with open(SCHEDULE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _media_url(rel):
    return f"{config.MEDIA_BASE_URL.rstrip('/')}/{os.path.basename(rel)}"


def _is_due(post, now_utc, overrides):
    o = overrides.get(post["id"], {})
    date = o.get("date", post["date"])
    time = o.get("time", post["time"])
    tz = ZoneInfo(post.get("tz", "America/New_York"))
    scheduled = datetime.datetime.fromisoformat(f"{date}T{time}").replace(tzinfo=tz)
    return now_utc >= scheduled


def _caption(post, for_linkedin=False):
    parts = [post.get("caption_en", "").strip()]
    if not for_linkedin:
        parts.append(post.get("caption_es", "").strip())
    parts.append(post.get("hashtags", "").strip())
    return "\n\n".join(p for p in parts if p)


def _publish_one(platform, post, media, cap):
    ptype = post.get("type", "carousel")
    if platform == "instagram":
        if ptype == "reel":
            resp = instagram.publish_reel(media[0], cap)
        elif len(media) > 1:
            resp = instagram.publish_carousel(media, cap)
        else:
            resp = instagram.publish_single(media[0], cap)
        return resp.get("id")
    if platform == "facebook":
        resp = facebook.publish_video(media[0], cap) if ptype == "reel" else facebook.publish_images(media, cap)
        return resp.get("id") or resp.get("post_id")
    if platform == "linkedin":
        return linkedin.publish_image(media[0], _caption(post, for_linkedin=True))
    raise ValueError(f"unknown platform {platform}")


def run():
    now = datetime.datetime.now(datetime.timezone.utc)
    posts = yaml.safe_load(open(POSTS_FILE))["posts"]
    overrides = _overrides()
    sent = 0
    for post in posts:
        if not _is_due(post, now, overrides):
            continue
        pid = post["id"]
        media = [_media_url(m) for m in post.get("media", [])]
        cap = _caption(post)
        for platform in post.get("platforms", []):
            if state.is_published(pid, platform):
                continue
            try:
                ref = _publish_one(platform, post, media, cap)
                state.mark(pid, platform, ref)
                sent += 1
                print(f"PUBLISHED {pid} -> {platform} ({ref})")
            except Exception as e:  # one platform failing shouldn't block the others
                print(f"FAILED {pid} -> {platform}: {e}", file=sys.stderr)
    print(f"done. {sent} post(s) published this run.")


if __name__ == "__main__":
    run()
