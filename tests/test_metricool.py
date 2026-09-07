"""tools/metricool.py — edits stay ONE row, and the dashboard build never hides a
failed read behind an empty list.

Live semantics these tests pin (verified 2026-09-07 on a throwaway draft):
  PUT with id+uuid in the body replaces the row; PUT without id creates a copy and
  leaves the old row; a copied GET row (provider statuses) makes the PUT 500."""
import json
import os
import sys

import pytest

from conftest import ROOT, FakeResponse

sys.path.insert(0, os.path.join(ROOT, "tools"))
import metricool  # noqa: E402


def _row(pid, uuid, dt="2026-12-30T10:00:00", status="PENDING", text="t", published=None):
    prov = [{"network": "instagram", "status": status}, {"network": "facebook", "status": status}]
    return {"id": pid, "uuid": uuid, "text": text, "draft": False, "autoPublish": True,
            "media": ["https://ortizia2000.github.io/sprig/media/x-1.jpg"], "mediaAltText": [],
            "publicationDate": {"dateTime": dt, "timezone": "America/New_York"},
            "creationDate": {"dateTime": "2026-09-06T00:37:00", "timezone": "America/New_York"},
            "creatorUserMail": "nelly@example.com", "providers": prov,
            "facebookData": {"type": "POST", "boost": 0}, "instagramData": {"type": "POST"},
            "firstCommentText": "", "hasNotReadNotes": False, "shortener": False,
            "smartLinkData": {"ids": []}, "saveExternalMediaFiles": False}


class FakeMetricool:
    """In-memory Metricool with the real quirks: a PUT re-ids the row; a PUT whose
    body lacks `id` leaves the old row and adds a new one; stale id -> 404;
    provider statuses in the body -> 500."""

    def __init__(self, rows):
        self.rows = {r["id"]: r for r in rows}
        self.next_id = max(self.rows, default=100) + 1
        self.calls = []

    def _id_from(self, url):
        return int(url.rstrip("/").split("/")[-1])

    def get(self, url, headers=None, timeout=None, params=None):
        self.calls.append(("get", params))
        return FakeResponse(200, {"data": list(self.rows.values())})

    def put(self, url, headers=None, timeout=None, params=None, data=None):
        pid = self._id_from(url)
        body = json.loads(data)
        self.calls.append(("put", pid, body))
        if pid not in self.rows:
            return FakeResponse(404, {"status": "NOT_FOUND"})
        if any("status" in p for p in body.get("providers", [])):
            return FakeResponse(500, {"detail": "PublicationStatusCode"})
        old = self.rows[pid]
        new = dict(old)
        new.update({k: v for k, v in body.items() if k not in ("id", "providers")})
        new["providers"] = [{"network": p["network"], "status": "PENDING"} for p in body["providers"]]
        new["id"] = self.next_id
        self.next_id += 1
        if body.get("id") == pid:           # edit in place: the old row goes away
            del self.rows[pid]
        self.rows[new["id"]] = new
        return FakeResponse(200, {"data": new})

    def delete(self, url, headers=None, timeout=None, params=None):
        pid = self._id_from(url)
        self.calls.append(("delete", pid))
        if pid not in self.rows:
            return FakeResponse(404, {"status": "NOT_FOUND"})
        del self.rows[pid]
        return FakeResponse(200, {"data": True})


def client(fake):
    return metricool.Client(token="t", user_id="1", http=fake)


def test_write_body_strips_read_only_fields_and_zero_boost():
    body = metricool.write_body(_row(1, "u"))
    assert body["providers"] == [{"network": "instagram"}, {"network": "facebook"}]
    assert "creationDate" not in body and "creatorUserMail" not in body and "id" not in body
    assert "boost" not in body["facebookData"]           # boost: 0 = 400 on Facebook
    assert body["text"] == "t" and body["publicationDate"]["dateTime"] == "2026-12-30T10:00:00"


def test_update_edits_in_place_and_sends_id_plus_uuid():
    fake = FakeMetricool([_row(10, "u1", text="v1")])
    row, deleted = client(fake).update("u1", {"text": "v2"}, "2026-12-01", "2026-12-31")
    put = next(c for c in fake.calls if c[0] == "put")
    assert put[1] == 10 and put[2]["id"] == 10 and put[2]["uuid"] == "u1"
    assert put[2]["text"] == "v2" and all("status" not in p for p in put[2]["providers"])
    assert row["text"] == "v2" and deleted == []
    assert [r["uuid"] for r in fake.rows.values()] == ["u1"]        # exactly one row


def test_update_uses_the_current_id_not_the_one_the_caller_remembers():
    # The row was re-id'd by an earlier write: 10 is gone, 11 is current.
    fake = FakeMetricool([_row(11, "u1", text="v1")])
    client(fake).update("u1", {"text": "v2"}, "2026-12-01", "2026-12-31")
    put = next(c for c in fake.calls if c[0] == "put")
    assert put[1] == 11


def test_update_removes_the_copy_a_write_left_behind():
    fake = FakeMetricool([_row(10, "u1", text="v1")])

    real_put = fake.put

    def duplicating_put(url, **kw):       # a Metricool that ignores `id` and copies
        body = json.loads(kw["data"])
        body.pop("id", None)
        kw["data"] = json.dumps(body)
        return real_put(url, **kw)

    fake.put = duplicating_put
    row, deleted = client(fake).update("u1", {"text": "v2"}, "2026-12-01", "2026-12-31")
    assert deleted == [10]                          # the stale copy is gone
    assert row["text"] == "v2"
    assert [r["text"] for r in fake.rows.values()] == ["v2"]


def test_update_never_deletes_a_published_row():
    fake = FakeMetricool([_row(10, "u1", status="PUBLISHED", text="went out"),
                          _row(12, "u1", text="pending")])
    row, deleted = client(fake).update("u1", {"text": "v2"}, "2026-12-01", "2026-12-31")
    assert 10 in fake.rows and fake.rows[10]["text"] == "went out"
    assert deleted == [] and row["text"] == "v2"


def test_update_unknown_uuid_is_an_error_not_a_create():
    fake = FakeMetricool([_row(10, "u1")])
    with pytest.raises(metricool.MetricoolError, match="no scheduled post"):
        client(fake).update("nope", {"text": "x"}, "2026-12-01", "2026-12-31")
    assert not any(c[0] in ("put", "delete") for c in fake.calls)


def test_dedupe_keeps_newest_pending_copy_and_leaves_history():
    fake = FakeMetricool([_row(1, "a", status="PUBLISHED"), _row(2, "a"), _row(3, "a"),
                          _row(4, "b")])
    dry = client(fake).dedupe("2026-12-01", "2026-12-31")
    assert dry == [("a", 3, [2])] and set(fake.rows) == {1, 2, 3, 4}
    client(fake).dedupe("2026-12-01", "2026-12-31", apply=True)
    assert set(fake.rows) == {1, 3, 4}


def test_duplicates_counts_pending_copies_only():
    rows = [_row(1, "a", status="PUBLISHED"), _row(2, "a"), _row(3, "a"), _row(4, "b")]
    assert metricool.duplicates(rows) == {"a": [2, 3]}


def test_transport_error_is_loud():
    class Down:
        def get(self, *a, **k):
            return FakeResponse(503, {"status": "down"})

    with pytest.raises(metricool.MetricoolError, match="503"):
        metricool.Client(token="t", user_id="1", http=Down()).list("2026-12-01", "2026-12-31")


def test_client_refuses_to_start_without_credentials(monkeypatch):
    monkeypatch.delenv("METRICOOL_TOKEN", raising=False)
    monkeypatch.delenv("METRICOOL_USER_ID", raising=False)
    monkeypatch.setattr(metricool, "_read_file", lambda p: "")
    with pytest.raises(metricool.MetricoolError, match="not configured"):
        metricool.Client()


def test_cli_update_builds_a_publication_date_patch(monkeypatch, tmp_path, capsys):
    fake = FakeMetricool([_row(10, "u1")])
    c = client(fake)
    monkeypatch.setattr(metricool, "Client", lambda **k: c)
    cap = tmp_path / "c.txt"
    cap.write_text("new caption\n")
    rc = metricool.main(["update", "u1", "--date", "2026-12-24", "--time", "09:30",
                         "--text-file", str(cap), "--start", "2026-12-01", "--end", "2026-12-31"])
    assert rc == 0
    put = next(c for c in fake.calls if c[0] == "put")[2]
    assert put["publicationDate"] == {"dateTime": "2026-12-24T09:30:00", "timezone": "America/New_York"}
    assert put["text"] == "new caption"
    assert "updated" in capsys.readouterr().out


# ---- build_data: the dashboard must show the Metricool queue, and say when it can't ----

def test_build_data_reports_unconfigured_not_empty(monkeypatch):
    import build_data
    monkeypatch.setattr(metricool, "configured", lambda: False)
    sec = build_data.metricool_section()
    assert sec["status"] == "unconfigured" and sec["posts"] == []


def test_build_data_summarizes_rows_and_flags_duplicates(monkeypatch):
    import build_data
    fake = FakeMetricool([_row(1, "a", status="PUBLISHED", dt="2026-09-06T11:30:00"),
                          _row(2, "a", dt="2026-09-07T15:00:00"), _row(3, "a", dt="2026-09-07T15:00:00")])
    c = client(fake)
    monkeypatch.setattr(metricool, "configured", lambda: True)
    monkeypatch.setattr(metricool, "Client", lambda **k: c)
    sec = build_data.metricool_section()
    assert sec["status"] == "ok" and len(sec["posts"]) == 3
    assert sec["duplicates"] == {"a": [2, 3]}
    p = sec["posts"][0]
    assert p["date"] == "2026-09-06" and p["time"] == "11:30" and p["networks"]["instagram"] == "PUBLISHED"
    assert p["media"] == ["https://ortizia2000.github.io/sprig/media/x-1.jpg"]


def test_build_data_read_failure_is_a_status_not_a_crash(monkeypatch):
    import build_data

    class Down:
        def get(self, *a, **k):
            return FakeResponse(503, {"status": "down"})

    c = metricool.Client(token="t", user_id="1", http=Down())
    monkeypatch.setattr(metricool, "configured", lambda: True)
    monkeypatch.setattr(metricool, "Client", lambda **k: c)
    sec = build_data.metricool_section()
    assert sec["status"] == "error" and "503" in sec["error"] and sec["posts"] == []
