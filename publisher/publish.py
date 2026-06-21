"""Entry point. Reads content/posts.yaml, publishes any post that is due and
not yet sent, and records what went out. Run hourly by GitHub Actions.

    python -m publisher.publish
"""
import datetime
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


def _media_url(rel):
    return f"{config.MEDIA_BASE_URL.rstrip('/')}/{os.path.basename(rel)}"


def _is_due(post, now_utc):
    tz = ZoneInfo(post.get("tz", "America/New_York"))
    scheduled = datetime.datetime.fromisoformat(f"{post['date']}T{post['time']}").replace(tzinfo=tz)
    return now_utc >= scheduled


def _caption(post, for_linkedin=False):
    parts = [post.get("caption_en", "").strip()]
    if not for_linkedin:
        parts.append(post.get("caption_es", "").strip())
    parts.append(post.get("hashtags", "").strip())
    return "\n\n".join(p for p in parts if p)


def run():
    now = datetime.datetime.now(datetime.timezone.utc)
    posts = yaml.safe_load(open(POSTS_FILE))["posts"]
    sent = 0
    for post in posts:
        if not _is_due(post, now):
            continue
        pid = post["id"]
        media = [_media_url(m) for m in post.get("media", [])]
        ptype = post.get("type", "carousel")
        for platform in post.get("platforms", []):
            if state.is_published(pid, platform):
                continue
            try:
                cap = _caption(post)
                if platform == "instagram":
                    if ptype == "reel":
                        instagram.publish_reel(media[0], cap)
                    elif len(media) > 1:
                        instagram.publish_carousel(media, cap)
                    else:
                        instagram.publish_single(media[0], cap)
                elif platform == "facebook":
                    if ptype == "reel":
                        facebook.publish_video(media[0], cap)
                    else:
                        facebook.publish_images(media, cap)
                elif platform == "linkedin":
                    linkedin.publish_image(media[0], _caption(post, for_linkedin=True))
                else:
                    raise ValueError(f"unknown platform {platform}")
                state.mark(pid, platform)
                sent += 1
                print(f"PUBLISHED {pid} -> {platform}")
            except Exception as e:  # keep going; one platform failing shouldn't block others
                print(f"FAILED {pid} -> {platform}: {e}", file=sys.stderr)
    print(f"done. {sent} post(s) published this run.")


if __name__ == "__main__":
    run()
