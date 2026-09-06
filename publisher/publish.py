"""Entry point. Reads content/posts.yaml, publishes any post that is due and
not yet sent, and records what went out (with the returned media id for metrics).

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

from . import config, facebook, instagram, linkedin, overrides, state, tiktok

ROOT = os.path.dirname(os.path.dirname(__file__))
# SPRIG_* env overrides let tests/experiments run against a scratch queue
POSTS_FILE = os.environ.get("SPRIG_POSTS_FILE") or os.path.join(ROOT, "content", "posts.yaml")
SCHEDULE_FILE = os.environ.get("SPRIG_SCHEDULE_FILE") or os.path.join(ROOT, "content", "schedule.json")


def _overrides():
    """Per-post overrides set from the dashboard (reschedule / approve / edit /
    delete / replace media). See publisher/overrides.py for the schema."""
    return overrides.load(SCHEDULE_FILE)


def _media_url(rel):
    return f"{config.MEDIA_BASE_URL.rstrip('/')}/{os.path.basename(rel)}"


# A post whose slot passed more than this long ago is stale, not due. Without the
# guard, the first run after a token outage fires the whole backlog at once — the
# queue sat unpublished from 2026-06-21 to 2026-08-30, so a valid token would have
# dumped five 10-week-old posts in one go. Re-date the post (or the dashboard's
# schedule override) to publish it late on purpose.
MAX_LATE_HOURS = float(os.environ.get("SPRIG_MAX_LATE_HOURS") or 48)


def _scheduled_at(post):
    """`post` already has its overrides applied (see run())."""
    tz = ZoneInfo(post.get("tz", "America/New_York"))
    return datetime.datetime.fromisoformat(f"{post['date']}T{post['time']}").replace(tzinfo=tz)


def _is_due(post, now_utc):
    # Borrado desde el dashboard: sale de la cola sin tocar posts.yaml. Se
    # revierte quitando la clave en content/schedule.json.
    if post.get("deleted"):
        print(f"DELETED {post['id']}: borrado desde el dashboard, no se publica")
        return False
    # Retenido a proposito: esperando aprobacion. No se publica aunque la fecha
    # haya pasado. Lo libera el boton Aprobar del dashboard (override
    # `review: false` + fecha nueva) o quitar `review: true` de posts.yaml.
    if post.get("review"):
        print(f"REVIEW {post['id']}: en revision, no se publica")
        return False
    scheduled = _scheduled_at(post)
    if now_utc < scheduled:
        return False
    late_hours = (now_utc - scheduled).total_seconds() / 3600
    if late_hours > MAX_LATE_HOURS:
        print(f"STALE {post['id']}: slot was {late_hours / 24:.1f} days ago, skipping "
              f"(re-date it, or raise SPRIG_MAX_LATE_HOURS, to publish it late)")
        return False
    return True


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
    if platform == "tiktok":
        if ptype != "reel":
            raise RuntimeError("TikTok is video-only — only reel posts can list `tiktok`")
        return tiktok.publish_video(media[0], _caption(post))
    if platform == "linkedin":
        if ptype == "reel":
            raise RuntimeError(
                "LinkedIn video posting not supported — keep `linkedin` off reel posts"
            )
        return linkedin.publish_image(media[0], _caption(post, for_linkedin=True))
    raise ValueError(f"unknown platform {platform}")


def run():
    """Publish everything due; returns the number of failed attempts."""
    now = datetime.datetime.now(datetime.timezone.utc)
    ov = _overrides()
    posts = [overrides.apply(p, ov) for p in yaml.safe_load(open(POSTS_FILE))["posts"]]
    sent = 0
    failed = 0
    for post in posts:
        if not _is_due(post, now):
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
                failed += 1
                print(f"FAILED {pid} -> {platform}: {e}", file=sys.stderr)
    print(f"done. {sent} post(s) published this run.")
    if failed:
        print(f"{failed} publish attempt(s) FAILED — will retry next run.", file=sys.stderr)
    return failed


def main():
    """Non-zero exit when anything failed, so the Actions run shows red.
    State for the posts that did go out is already on disk (state.mark),
    and the workflow's commit step runs regardless (if: always())."""
    return 1 if run() else 0


if __name__ == "__main__":
    sys.exit(main())
