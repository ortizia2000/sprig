"""Metricool scheduler client — the rail that actually publishes @myceliumai.co
since 2026-09-06 (Sprig itself only hosts the media and shows the queue).

Why this exists: Metricool's PUT is not an edit-in-place unless the body carries
the post's CURRENT `id` and its `uuid`. Verified 2026-09-07 against the live API:

    PUT /posts/{id}  body with id+uuid      -> replaces the row (new id, one row)
    PUT /posts/{id}  body WITHOUT id        -> creates a second row, old one stays
    PUT /posts/{stale id}                   -> 404
    body copied from GET (provider statuses) -> 500 PublicationStatusCode

The banquete carousel was "updated" three times on 2026-09-06 that way and every
copy published on its own. `Client.update` does the whole dance: re-read the current
id, PUT with id+uuid, re-read, delete any copy the write left behind, and refuse to
return until exactly one row carries that uuid.

    python tools/metricool.py list [--start 2026-09-01 --end 2026-12-31]
    python tools/metricool.py update <uuid> --date 2026-09-20 --time 15:00
    python tools/metricool.py update <uuid> --text-file caption.txt
    python tools/metricool.py delete <id>
    python tools/metricool.py dedupe [--apply]      # pending copies of one uuid -> keep newest

Credentials: METRICOOL_TOKEN + METRICOOL_USER_ID (GitHub secrets), or locally the
files ~/.metricool-token and ~/.metricool-id. Never printed, never committed.
"""
import argparse
import datetime
import json
import os
import sys

import requests

BASE_URL = os.environ.get("METRICOOL_BASE_URL") or "https://app.metricool.com/api"
BLOG_ID = int(os.environ.get("METRICOOL_BLOG_ID") or 6434975)   # Mycelium brand in Metricool
TZ = "America/New_York"
TIMEOUT = 30
# The fields Metricool's write bean accepts. Everything else a GET row carries
# (creationDate, creatorUserMail, provider statuses...) makes the PUT 500.
WRITE_KEYS = (
    "autoPublish", "draft", "firstCommentText", "hasNotReadNotes", "media", "mediaAltText",
    "publicationDate", "shortener", "smartLinkData", "text", "saveExternalMediaFiles",
    "descendants", "twitterData", "facebookData", "instagramData", "linkedinData",
    "pinterestData", "youtubeData", "tiktokData", "blueskyData", "threadsData", "twitchData",
)


class MetricoolError(RuntimeError):
    pass


def _read_file(path):
    try:
        with open(os.path.expanduser(path)) as f:
            return f.read().strip()
    except OSError:
        return ""


def credentials():
    """Token + user id from the environment, else from the local dotfiles."""
    token = os.environ.get("METRICOOL_TOKEN") or _read_file("~/.metricool-token")
    user_id = os.environ.get("METRICOOL_USER_ID") or _read_file("~/.metricool-id")
    return token, user_id


def configured():
    token, user_id = credentials()
    return bool(token and user_id)


def write_body(row):
    """A GET row turned into something PUT accepts: write keys only, providers reduced
    to their network name, and the `boost: 0` that breaks Facebook posts dropped."""
    body = {k: row[k] for k in WRITE_KEYS if k in row}
    body["providers"] = [{"network": p["network"]} for p in row.get("providers", []) if p.get("network")]
    for k in ("facebookData", "instagramData"):
        d = body.get(k)
        if isinstance(d, dict):
            for bk in ("boost", "boostPayer", "boostBeneficiary"):
                if not d.get(bk):
                    d.pop(bk, None)
    return body


def _status(row):
    return {p.get("network"): p.get("status") for p in row.get("providers", []) if p.get("network")}


def is_published(row):
    return any(s == "PUBLISHED" for s in _status(row).values())


def default_window(today=None, back_days=14, ahead_days=120):
    today = today or datetime.date.today()
    return (today - datetime.timedelta(days=back_days)).isoformat(), \
           (today + datetime.timedelta(days=ahead_days)).isoformat()


class Client:
    def __init__(self, token=None, user_id=None, blog_id=BLOG_ID, http=None, base_url=BASE_URL):
        if token is None or user_id is None:
            t, u = credentials()
            token, user_id = token or t, user_id or u
        if not token or not user_id:
            raise MetricoolError("METRICOOL_TOKEN / METRICOOL_USER_ID not configured "
                                 "(env, or ~/.metricool-token + ~/.metricool-id)")
        self.token, self.user_id, self.blog_id = token, str(user_id), int(blog_id)
        self.http = http or requests
        self.base = base_url.rstrip("/")

    # ---- transport -------------------------------------------------------
    def _headers(self):
        return {"X-Mc-Auth": self.token, "content-type": "application/json", "accept": "application/json"}

    def _params(self, **extra):
        p = {"blogId": self.blog_id, "userId": self.user_id, "integrationSource": "sprig"}
        p.update(extra)
        return p

    def _call(self, method, path, **kw):
        fn = getattr(self.http, method)
        try:
            r = fn(f"{self.base}/{path}", headers=self._headers(), timeout=TIMEOUT, **kw)
        except requests.RequestException as e:
            raise MetricoolError(f"Metricool unreachable ({method.upper()} {path}): {e}") from e
        if not r.ok:
            raise MetricoolError(f"Metricool {r.status_code} on {method.upper()} {path}: {r.text[:300]}")
        try:
            return r.json()
        except ValueError as e:
            raise MetricoolError(f"Metricool returned non-JSON on {method.upper()} {path}") from e

    # ---- reads -------------------------------------------------------------
    def list(self, start, end):
        """Every scheduler row whose publication date falls in [start, end] (YYYY-MM-DD)."""
        data = self._call("get", "v2/scheduler/posts", params=self._params(
            start=f"{start}T00:00:00", end=f"{end}T23:59:59", timezone=TZ, extendedRange="false"))
        rows = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise MetricoolError(f"unexpected scheduler payload: {str(data)[:200]}")
        return rows

    def rows_for(self, uuid, start, end):
        return sorted((r for r in self.list(start, end) if r.get("uuid") == uuid), key=lambda r: r["id"])

    # ---- writes ------------------------------------------------------------
    def delete(self, post_id):
        self._call("delete", f"v2/scheduler/posts/{post_id}", params=self._params())
        return post_id

    def update(self, uuid, patch, start=None, end=None):
        """Edit ONE scheduled post in place. Returns (final_row, deleted_ids).

        Re-reads the current id first (a stale id is a 404), sends the full write body
        with id + uuid (without them Metricool creates a copy), then re-reads and deletes
        any copy the write left, so that exactly one row carries the uuid afterwards."""
        start, end = (start, end) if start and end else default_window()
        rows = self.rows_for(uuid, start, end)
        if not rows:
            raise MetricoolError(f"no scheduled post with uuid {uuid} between {start} and {end}")
        pending = [r for r in rows if not is_published(r)] or rows
        current = pending[-1]
        body = write_body(current)
        body.update(patch)
        body["id"], body["uuid"] = current["id"], uuid
        result = self._call("put", f"v2/scheduler/posts/{current['id']}", params=self._params(),
                            data=json.dumps(body))
        new_id = (result.get("data") or {}).get("id") if isinstance(result, dict) else None
        after = self.rows_for(uuid, start, end)
        keep = new_id if new_id in {r["id"] for r in after} else (after[-1]["id"] if after else None)
        deleted = []
        for r in after:
            if r["id"] != keep and not is_published(r):
                self.delete(r["id"])
                deleted.append(r["id"])
        final = [r for r in self.rows_for(uuid, start, end) if not is_published(r)]
        if len(final) != 1:
            raise MetricoolError(f"after update, uuid {uuid} has {len(final)} pending rows "
                                 f"({[r['id'] for r in final]}); expected exactly 1 — fix in Metricool before it publishes")
        return final[0], deleted

    def dedupe(self, start=None, end=None, apply=False):
        """Pending copies of one uuid: keep the newest id, delete the rest. Published
        rows are history and are never touched. Returns [(uuid, kept_id, [deleted ids])]."""
        start, end = (start, end) if start and end else default_window()
        groups = {}
        for r in self.list(start, end):
            if not is_published(r):
                groups.setdefault(r.get("uuid"), []).append(r)
        actions = []
        for uuid, rows in groups.items():
            if len(rows) < 2:
                continue
            rows.sort(key=lambda r: r["id"])
            keep, extras = rows[-1]["id"], [r["id"] for r in rows[:-1]]
            if apply:
                for pid in extras:
                    self.delete(pid)
            actions.append((uuid, keep, extras))
        return actions


# ---- dashboard shape -----------------------------------------------------------
def summarize(row):
    pub = row.get("publicationDate") or {}
    dt = str(pub.get("dateTime") or "")
    return {
        "id": row.get("id"),
        "uuid": row.get("uuid"),
        "date": dt[:10],
        "time": dt[11:16],
        "tz": pub.get("timezone") or TZ,
        "networks": _status(row),
        "text": (row.get("text") or "").strip(),
        "media": list(row.get("media") or []),
        "draft": bool(row.get("draft")),
        "autoPublish": bool(row.get("autoPublish", True)),
    }   # no creator e-mail: data.json is public


def duplicates(rows):
    """uuids that have more than one PENDING row — each copy will publish separately."""
    seen = {}
    for r in rows:
        if not is_published(r):
            seen.setdefault(r.get("uuid"), []).append(r["id"])
    return {u: ids for u, ids in seen.items() if len(ids) > 1}


# ---- CLI -----------------------------------------------------------------------
def _print_rows(rows):
    for r in sorted(rows, key=lambda x: (x.get("publicationDate") or {}).get("dateTime", "")):
        s = summarize(r)
        nets = " ".join(f"{n}:{st}" for n, st in s["networks"].items())
        print(f"{s['id']:>10}  {s['uuid']:>22}  {s['date']} {s['time']}  {nets:<40} {s['text'][:50]!r}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "dedupe"):
        s = sub.add_parser(name)
        s.add_argument("--start")
        s.add_argument("--end")
    sub.choices["list"].add_argument("--json", action="store_true")
    sub.choices["dedupe"].add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    u = sub.add_parser("update")
    u.add_argument("uuid")
    u.add_argument("--date")
    u.add_argument("--time")
    u.add_argument("--text-file", help="file whose whole content becomes the post text")
    u.add_argument("--media", help="comma-separated public URLs (replaces the list)")
    u.add_argument("--start")
    u.add_argument("--end")
    d = sub.add_parser("delete")
    d.add_argument("id", type=int)
    a = ap.parse_args(argv)

    c = Client()
    if a.cmd == "list":
        start, end = (a.start, a.end) if a.start and a.end else default_window()
        rows = c.list(start, end)
        if a.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            _print_rows(rows)
            dup = duplicates(rows)
            for uuid, ids in dup.items():
                print(f"DUPLICATE uuid {uuid}: {len(ids)} pending copies {ids} — each one publishes", file=sys.stderr)
        return 0
    if a.cmd == "delete":
        c.delete(a.id)
        print(f"deleted {a.id}")
        return 0
    if a.cmd == "dedupe":
        acts = c.dedupe(a.start, a.end, apply=a.apply)
        if not acts:
            print("no pending duplicates")
        for uuid, keep, extras in acts:
            print(f"{'deleted' if a.apply else 'would delete'} {extras} · kept {keep} · uuid {uuid}")
        if acts and not a.apply:
            print("dry run — re-run with --apply", file=sys.stderr)
        return 0
    if a.cmd == "update":
        patch = {}
        if a.date or a.time:
            if not (a.date and a.time):
                ap.error("--date and --time go together")
            patch["publicationDate"] = {"dateTime": f"{a.date}T{a.time}:00", "timezone": TZ}
        if a.text_file:
            with open(a.text_file) as f:
                patch["text"] = f.read().strip()
        if a.media:
            patch["media"] = [m.strip() for m in a.media.split(",") if m.strip()]
        if not patch:
            ap.error("nothing to change: pass --date/--time, --text-file or --media")
        row, deleted = c.update(a.uuid, patch, a.start, a.end)
        s = summarize(row)
        print(f"updated · id {s['id']} · {s['date']} {s['time']} {s['tz']} · {list(s['networks'])}")
        if deleted:
            print(f"removed {len(deleted)} copy(ies) the write left behind: {deleted}", file=sys.stderr)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
