"""tools/export_to_runtime.py — moves Sprig's queue into the Mycelium publish rail.

The runtime side (MYC-4534) is not live yet, so every test here runs against a
fake HTTP server that implements exactly the wire contract in
`Specs/Sprig Publish Rail Spec.md` (Leg 1). Nothing here talks to the network.
"""
import http.server
import json
import os
import threading

import pytest
import yaml

from conftest import ROOT  # noqa: F401  (puts tools/ + repo root on sys.path)
from publisher import publish, state

import export_to_runtime as ex

HELD = {
    "id": "p1",
    "review": True,
    "date": "2026-06-21",
    "time": "12:00",
    "tz": "America/New_York",
    "platforms": ["instagram", "facebook"],
    "type": "carousel",
    "media": ["a.png", "b.png"],
    "caption_en": "hello",
    "caption_es": "hola",
    "hashtags": "#x",
}
APPROVED = {**HELD, "id": "p2", "review": False, "media": ["c.png"], "platforms": ["instagram"]}


class _Handler(http.server.BaseHTTPRequestHandler):
    """Implements GET /publish/queue, POST /publish/media, POST /publish/queue,
    POST /publish/queue/{id}/approve. Records every call it receives."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # keep pytest output clean
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _send(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _record(self, method):
        body = self._body()
        self.server.calls.append({
            "method": method,
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type", ""),
            "body": body,
        })
        return body

    def do_GET(self):
        self._record("GET")
        self._send(200, {"ok": True, "rows": self.server.rows,
                         "published_count": 0, "failed_count": 0, "window_days": 7})

    def do_POST(self):
        body = self._record("POST")
        if self.server.fail_on and self.server.fail_on[0] in self.path:
            return self._send(self.server.fail_on[1], {"detail": self.server.fail_on[2]})
        if self.path.startswith("/publish/media"):
            self.server.seq += 1
            return self._send(201, {"media_id": f"pm_{self.server.seq}", "kind": "image",
                                    "content_type": "image/png", "bytes": len(body),
                                    "public_url": "https://x/public/media/v1.x",
                                    "created_at": "2026-09-07T00:00:00+00:00"})
        if self.path.endswith("/approve"):
            return self._send(200, {"id": self.path.split("/")[3], "status": "queued"})
        if self.path.startswith("/publish/queue"):
            self.server.seq += 1
            row_id = f"pq_{self.server.seq}"
            sent = json.loads(body)
            self.server.rows.append({"id": row_id, "status": "held", "source": sent.get("source")})
            return self._send(201, {"id": row_id, "status": "held", **sent})
        self._send(404, {"detail": "no route"})


@pytest.fixture
def runtime(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.calls, srv.rows, srv.seq, srv.fail_on = [], [], 0, None
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setenv("MYCELIUM_RUNTIME_URL", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setenv("MYCELIUM_RUNTIME_TOKEN", "tok-123")
    yield srv
    srv.shutdown()
    srv.server_close()
    t.join(timeout=5)


@pytest.fixture
def queue(tmp_path, monkeypatch):
    """posts.yaml + schedule.json + published.json + media, all under tmp_path."""
    def build(posts, schedule=None, published=None, media=("a.png", "b.png", "c.png")):
        (tmp_path / "posts.yaml").write_text(yaml.safe_dump({"posts": posts}))
        (tmp_path / "schedule.json").write_text(json.dumps(schedule or {}))
        (tmp_path / "published.json").write_text(json.dumps(published or {}))
        mdir = tmp_path / "media"
        mdir.mkdir(exist_ok=True)
        for i, name in enumerate(media):
            (mdir / name).write_bytes(bytes([i]) * (10 + i))
        monkeypatch.setattr(publish, "POSTS_FILE", str(tmp_path / "posts.yaml"))
        monkeypatch.setattr(publish, "SCHEDULE_FILE", str(tmp_path / "schedule.json"))
        monkeypatch.setattr(state, "STATE_FILE", str(tmp_path / "published.json"))
        monkeypatch.setattr(ex, "MEDIA_DIR", str(mdir))
        return tmp_path
    return build


def _posts(srv):
    return [c for c in srv.calls if c["method"] == "POST"]


# --- dry run -------------------------------------------------------------

def test_dry_run_is_the_default_and_makes_no_requests(queue, runtime, capsys):
    queue([dict(HELD), dict(APPROVED)])
    assert ex.main([]) == 0
    assert runtime.calls == []
    out = capsys.readouterr().out
    assert "p1" in out and "instagram" in out and "facebook" in out
    assert "held" in out and "queued" in out
    assert "2026-06-21T12:00:00-04:00" in out       # RFC3339 with the tz offset
    assert "dry run" in out.lower()


def test_dry_run_reports_media_count_and_bytes(queue, runtime, capsys):
    queue([dict(HELD)])
    ex.main([])
    out = capsys.readouterr().out
    # p1 carries a.png (10 bytes) + b.png (11 bytes)
    assert "21" in out
    assert runtime.calls == []


# --- apply ---------------------------------------------------------------

def test_apply_sends_media_then_queue_then_approve_only_for_approved_posts(queue, runtime):
    queue([dict(HELD), dict(APPROVED)])
    assert ex.main(["--apply"]) == 0

    paths = [(c["method"], c["path"]) for c in runtime.calls]
    assert paths[0] == ("GET", "/publish/queue?include_deleted=1")
    assert paths[1:5] == [
        ("POST", "/publish/media"),      # a.png
        ("POST", "/publish/media"),      # b.png
        ("POST", "/publish/queue"),      # p1 instagram (held -> no approve)
        ("POST", "/publish/queue"),      # p1 facebook, media already uploaded this run
    ]
    assert paths[5:] == [
        ("POST", "/publish/media"),                 # c.png
        ("POST", "/publish/queue"),                 # p2 instagram
        ("POST", "/publish/queue/pq_6/approve"),    # approved in Sprig -> approve here
    ]
    assert {c["auth"] for c in runtime.calls} == {"Bearer tok-123"}


def test_apply_queue_body_is_exact(queue, runtime):
    queue([dict(HELD)])
    ex.main(["--apply"])
    bodies = [json.loads(c["body"]) for c in _posts(runtime) if c["path"] == "/publish/queue"]
    assert bodies[0] == {
        "platform": "instagram",
        "caption": "hello\n\nhola\n\n#x",
        "media_ids": ["pm_1", "pm_2"],
        "scheduled_at": "2026-06-21T12:00:00-04:00",
        "source": "sprig:p1:instagram",
    }
    assert bodies[1]["platform"] == "facebook"
    assert bodies[1]["source"] == "sprig:p1:facebook"
    assert bodies[1]["media_ids"] == ["pm_1", "pm_2"]     # same order, same ids


def test_apply_uploads_the_file_bytes_under_the_file_field(queue, runtime):
    queue([dict(HELD, media=["a.png"], platforms=["instagram"])])
    ex.main(["--apply"])
    up = [c for c in _posts(runtime) if c["path"] == "/publish/media"][0]
    assert up["content_type"].startswith("multipart/form-data")
    assert b'name="file"; filename="a.png"' in up["body"]
    assert b"\x00" * 10 in up["body"]


def test_approve_carries_the_same_scheduled_at(queue, runtime):
    queue([dict(APPROVED)])
    ex.main(["--apply"])
    approve = [c for c in _posts(runtime) if c["path"].endswith("/approve")][0]
    assert json.loads(approve["body"]) == {"scheduled_at": "2026-06-21T12:00:00-04:00"}


def test_apply_prints_each_created_row_id(queue, runtime, capsys):
    queue([dict(APPROVED)])
    ex.main(["--apply"])
    assert "pq_2" in capsys.readouterr().out


# --- idempotency ---------------------------------------------------------

def test_second_apply_creates_nothing(queue, runtime, capsys):
    queue([dict(HELD), dict(APPROVED)])
    ex.main(["--apply"])
    runtime.calls.clear()
    assert ex.main(["--apply"]) == 0
    assert [(c["method"], c["path"]) for c in runtime.calls] == [
        ("GET", "/publish/queue?include_deleted=1")
    ]
    assert "skip" in capsys.readouterr().out.lower()


def test_rows_already_in_the_runtime_are_skipped_even_when_deleted_there(queue, runtime):
    queue([dict(APPROVED)])
    runtime.rows.append({"id": "pq_old", "status": "deleted", "source": "sprig:p2:instagram"})
    ex.main(["--apply"])
    assert _posts(runtime) == []


# --- what never gets exported -------------------------------------------

def test_deleted_override_and_already_published_are_skipped(queue, runtime):
    queue(
        [dict(HELD), dict(APPROVED)],
        schedule={"p1": {"deleted": True}},
        published={"p2": {"instagram": "ig1"}},
    )
    assert ex.main(["--apply"]) == 0
    assert _posts(runtime) == []


def test_only_instagram_and_facebook_are_exported(queue, runtime):
    queue([dict(APPROVED, platforms=["instagram", "linkedin", "tiktok"])])
    ex.main(["--apply"])
    bodies = [json.loads(c["body"]) for c in _posts(runtime) if c["path"] == "/publish/queue"]
    assert [b["platform"] for b in bodies] == ["instagram"]


def test_overrides_supply_caption_date_time_and_media(queue, runtime):
    queue(
        [dict(HELD)],
        schedule={"p1": {"date": "2026-10-01", "time": "09:00", "review": False,
                         "caption_en": "edited", "caption_es": "", "hashtags": "#new",
                         "media": ["c.png"]}},
    )
    ex.main(["--apply"])
    body = json.loads([c for c in _posts(runtime) if c["path"] == "/publish/queue"][0]["body"])
    assert body["caption"] == "edited\n\n#new"
    assert body["scheduled_at"] == "2026-10-01T09:00:00-04:00"
    assert body["media_ids"] == ["pm_1"]
    # review:false in the override means Sprig already approved it
    assert any(c["path"].endswith("/approve") for c in _posts(runtime))


# --- failure modes -------------------------------------------------------

@pytest.mark.parametrize("missing", ["MYCELIUM_RUNTIME_URL", "MYCELIUM_RUNTIME_TOKEN"])
def test_missing_env_exits_2_before_any_request(queue, runtime, monkeypatch, capsys, missing):
    queue([dict(APPROVED)])
    monkeypatch.delenv(missing)
    assert ex.main(["--apply"]) == 2
    assert runtime.calls == []
    assert missing in capsys.readouterr().err


def test_missing_env_exits_2_in_dry_run_too(queue, runtime, monkeypatch):
    queue([dict(APPROVED)])
    monkeypatch.delenv("MYCELIUM_RUNTIME_TOKEN")
    assert ex.main([]) == 2


def test_422_stops_with_exit_1_and_prints_the_runtime_detail(queue, runtime, capsys):
    queue([dict(HELD), dict(APPROVED)])
    runtime.fail_on = ("/publish/queue", 422, "caption is longer than 2200 characters")
    assert ex.main(["--apply"]) == 1
    assert "caption is longer than 2200 characters" in capsys.readouterr().err
    # stopped at the first failing row: p2's media was never uploaded
    assert len([c for c in _posts(runtime) if c["path"] == "/publish/media"]) == 2


def test_a_failed_media_upload_stops_before_the_queue_row(queue, runtime, capsys):
    queue([dict(HELD)])
    runtime.fail_on = ("/publish/media", 413, "media over cap")
    assert ex.main(["--apply"]) == 1
    assert "media over cap" in capsys.readouterr().err
    assert [c["path"] for c in _posts(runtime)] == ["/publish/media"]


def test_a_missing_media_file_stops_the_export(queue, runtime, capsys):
    queue([dict(APPROVED, media=["gone.png"])])
    assert ex.main(["--apply"]) == 1
    assert "gone.png" in capsys.readouterr().err
    assert _posts(runtime) == []


def test_nothing_to_export_is_not_an_error(queue, runtime, capsys):
    queue([], media=())
    assert ex.main(["--apply"]) == 0
    assert "nothing" in capsys.readouterr().out.lower()


def test_the_real_queue_exports_six_posts_across_two_platforms(monkeypatch):
    """Against the repo's own content/: the shape the operator will see."""
    monkeypatch.setattr(publish, "POSTS_FILE", os.path.join(ROOT, "content", "posts.yaml"))
    monkeypatch.setattr(publish, "SCHEDULE_FILE", os.path.join(ROOT, "content", "schedule.json"))
    monkeypatch.setattr(state, "STATE_FILE",
                        os.path.join(ROOT, "content", "state", "published.json"))
    monkeypatch.setattr(ex, "MEDIA_DIR", os.path.join(ROOT, "content", "media"))
    rows = ex.plan()
    assert len(rows) == 12                       # 6 posts x instagram + facebook
    assert all(r.held for r in rows)             # every one is review: true today
    assert all(r.media_bytes > 0 for r in rows)


def test_dry_run_totals_count_each_media_file_once(queue, runtime, capsys):
    """p1 is on two platforms and shares its two files; the transfer total is not doubled."""
    queue([dict(HELD)])
    ex.main([])
    out = capsys.readouterr().out
    assert "2 media file(s) to upload, 21 bytes" in out
