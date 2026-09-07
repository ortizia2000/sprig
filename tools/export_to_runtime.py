"""Move Sprig's queue into the Mycelium hosted publish rail (MYC-4537).

One row per (post, platform) is created in the runtime's publish queue, with the
same composed caption, the same media and the same slot Sprig would have used.
A post held in Sprig (`review: true`) lands `held` and waits for an approval in
Mycelium -> Spore -> Approvals; a post Sprig had already approved is approved
here too, so it keeps its slot.

    export MYCELIUM_RUNTIME_URL=https://mycelium-runtime.fly.dev
    export MYCELIUM_RUNTIME_TOKEN=...
    python tools/export_to_runtime.py             # dry run (default), writes nothing
    python tools/export_to_runtime.py --apply     # creates the rows

Idempotent: every row carries `source = "sprig:<post id>:<platform>"`, and the
export reads the whole queue once before writing, so a second `--apply` creates
nothing. Wire contract: `Specs/Sprig Publish Rail Spec.md` (Leg 1).
"""
import argparse
import mimetypes
import os
import sys

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from publisher import overrides, publish, state  # noqa: E402

# Only the two platforms the runtime rail owns. LinkedIn and TikTok stay on
# Sprig's own adapters until their apps are approved (spec, non-goals).
PLATFORMS = ("instagram", "facebook")
MEDIA_DIR = os.environ.get("SPRIG_MEDIA_DIR") or os.path.join(ROOT, "content", "media")
TIMEOUT = 120


class ExportError(Exception):
    """Anything that stops the export: a missing file or a runtime refusal."""


class MissingEnv(Exception):
    def __init__(self, name):
        super().__init__(name)
        self.name = name


class Row:
    """One (post, platform) pair, resolved to exactly what the runtime is sent."""

    def __init__(self, post_id, platform, caption, media, scheduled_at, held):
        self.post_id = post_id
        self.platform = platform
        self.caption = caption
        self.media = media                       # absolute paths, in order
        self.scheduled_at = scheduled_at         # RFC3339 with offset
        self.held = held
        self.source = f"sprig:{post_id}:{platform}"

    @property
    def media_bytes(self):
        return sum(os.path.getsize(p) for p in self.media if os.path.exists(p))

    @property
    def state(self):
        return "held" if self.held else "queued"


def _env():
    """Both variables or nothing — checked before any network call."""
    url = (os.environ.get("MYCELIUM_RUNTIME_URL") or "").strip()
    if not url:
        raise MissingEnv("MYCELIUM_RUNTIME_URL")
    token = (os.environ.get("MYCELIUM_RUNTIME_TOKEN") or "").strip()
    if not token:
        raise MissingEnv("MYCELIUM_RUNTIME_TOKEN")
    return url.rstrip("/"), token


def plan():
    """Every row this export would create, in the order it would create them.

    `publisher.publish._is_due` is deliberately NOT applied: due-ness now belongs
    to the runtime scheduler, and every post in Sprig's queue today is held with
    a slot in the past. The only skips are the dashboard's `deleted` flag and
    anything already sent from Sprig (content/state/published.json).
    """
    ov = publish._overrides()
    with open(publish.POSTS_FILE) as f:
        raw_posts = yaml.safe_load(f)["posts"]
    rows = []
    for raw in raw_posts:
        post = overrides.apply(raw, ov)
        if post.get("deleted"):
            continue
        caption = publish._caption(post)
        scheduled_at = publish._scheduled_at(post).isoformat()
        # `cover` is not uploaded: Instagram takes a reel's cover from the video.
        media = [os.path.join(MEDIA_DIR, os.path.basename(m)) for m in post.get("media") or []]
        for platform in post.get("platforms") or []:
            if platform not in PLATFORMS:
                continue
            if state.is_published(post["id"], platform):
                continue
            rows.append(Row(post["id"], platform, caption, media, scheduled_at,
                            bool(post.get("review"))))
    return rows


def _check(resp):
    """Runtime refusals carry the reason in `detail`; surface it and stop."""
    if resp.ok:
        return resp.json() if resp.content else {}
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = None
    raise ExportError(f"runtime {resp.status_code}: {detail or resp.text.strip() or '(no body)'}")


class Runtime:
    def __init__(self, base, token):
        self.base = base
        self.headers = {"Authorization": f"Bearer {token}"}

    def existing_sources(self):
        r = requests.get(f"{self.base}/publish/queue?include_deleted=1",
                         headers=self.headers, timeout=TIMEOUT)
        return {row.get("source") for row in _check(r).get("rows", []) if row.get("source")}

    def upload(self, path):
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            r = requests.post(f"{self.base}/publish/media", headers=self.headers,
                              files={"file": (os.path.basename(path), fh, ctype)},
                              timeout=TIMEOUT)
        return _check(r)["media_id"]

    def create(self, row, media_ids):
        r = requests.post(f"{self.base}/publish/queue", headers=self.headers, timeout=TIMEOUT,
                          json={"platform": row.platform, "caption": row.caption,
                                "media_ids": media_ids, "scheduled_at": row.scheduled_at,
                                "source": row.source})
        return _check(r)["id"]

    def approve(self, row_id, scheduled_at):
        r = requests.post(f"{self.base}/publish/queue/{row_id}/approve", headers=self.headers,
                          json={"scheduled_at": scheduled_at}, timeout=TIMEOUT)
        _check(r)


def _print_table(rows):
    head = ("post", "platform", "state", "scheduled_at", "media", "bytes")
    body = [(r.post_id, r.platform, r.state, r.scheduled_at, str(len(r.media)),
             f"{r.media_bytes:,}") for r in rows]
    widths = [max(len(c[i]) for c in [head, *body]) for i in range(len(head))]
    line = "  ".join(h.ljust(w) for h, w in zip(head, widths))
    print(line)
    print("  ".join("-" * w for w in widths))
    for cells in body:
        print("  ".join(c.ljust(w) for c, w in zip(cells, widths)))
    held = sum(1 for r in rows if r.held)
    # Each file is uploaded once per run even when two platforms share it, so the
    # transfer total counts unique files, not the per-row column above.
    files = {p for r in rows for p in r.media}
    print(f"\n{len(rows)} row(s): {held} held, {len(rows) - held} queued. "
          f"{len(files)} media file(s) to upload, "
          f"{sum(os.path.getsize(p) for p in files):,} bytes.")


def _verify_media(rows):
    for row in rows:
        for path in row.media:
            if not os.path.exists(path):
                raise ExportError(f"{row.post_id}: media file not found: {path}")


def run(apply=False):
    base, token = _env()                    # raises MissingEnv before any network
    rows = plan()
    if not rows:
        print("nothing to export: every post is deleted or already published.")
        return 0
    _verify_media(rows)

    if not apply:
        _print_table(rows)
        print("\ndry run: nothing was sent. Re-run with --apply to create these rows.")
        return 0

    rt = Runtime(base, token)
    existing = rt.existing_sources()
    uploaded = {}                            # path -> media_id, one upload per file per run
    created = 0
    for row in rows:
        if row.source in existing:
            print(f"skip {row.source}: already in the runtime queue")
            continue
        media_ids = []
        for path in row.media:
            if path not in uploaded:
                uploaded[path] = rt.upload(path)
                print(f"  uploaded {os.path.basename(path)} -> {uploaded[path]}")
            media_ids.append(uploaded[path])
        row_id = rt.create(row, media_ids)
        created += 1
        print(f"created {row_id}  {row.source}  {row.state}  {row.scheduled_at}")
        if not row.held:
            rt.approve(row_id, row.scheduled_at)
            print(f"  approved {row_id} for {row.scheduled_at}")
    print(f"\ndone. {created} row(s) created, {len(rows) - created} already there.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="actually create the rows (default is a dry run)")
    args = ap.parse_args(argv)
    try:
        return run(apply=args.apply)
    except MissingEnv as e:
        print(f"{e.name} is not set. Both MYCELIUM_RUNTIME_URL and "
              f"MYCELIUM_RUNTIME_TOKEN are required.", file=sys.stderr)
        return 2
    except ExportError as e:
        print(f"export stopped: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
