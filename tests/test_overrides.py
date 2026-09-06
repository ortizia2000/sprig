"""Dashboard overrides (content/schedule.json) — the layer the browser buttons write.
posts.yaml stays the source; the override file is merged on top of it by both the
publisher and the dashboard data build. Keys: date, time, review, deleted,
caption_en, caption_es, hashtags, media."""
import datetime
import json
import os
import sys

import pytest
import yaml
from zoneinfo import ZoneInfo

from conftest import ROOT
from publisher import overrides, publish, state

_DUE = datetime.datetime.now(ZoneInfo("America/New_York")) - datetime.timedelta(hours=1)
_DUE_DATE, _DUE_TIME = _DUE.strftime("%Y-%m-%d"), _DUE.strftime("%H:%M")

REVIEW_POST = {
    "id": "p1",
    "review": True,
    "date": "2026-06-21",          # long past: a stale slot from the YAML
    "time": "12:00",
    "tz": "America/New_York",
    "platforms": ["instagram"],
    "type": "carousel",
    "media": ["a.png"],
    "caption_en": "yaml caption",
    "hashtags": "#yaml",
}


@pytest.fixture
def q(tmp_path, monkeypatch):
    posts_file = tmp_path / "posts.yaml"
    posts_file.write_text(yaml.safe_dump({"posts": [dict(REVIEW_POST)]}))
    sched = tmp_path / "schedule.json"
    monkeypatch.setattr(publish, "POSTS_FILE", str(posts_file))
    monkeypatch.setattr(publish, "SCHEDULE_FILE", str(sched))
    monkeypatch.setattr(state, "STATE_FILE", str(tmp_path / "published.json"))
    sent = []
    monkeypatch.setattr(publish.instagram, "publish_single",
                        lambda url, cap: sent.append((url, cap)) or {"id": "ig1"})
    return sched, sent


def test_apply_merges_override_on_top_of_yaml():
    p = overrides.apply(REVIEW_POST, {"p1": {"review": False, "caption_en": "new"}})
    assert p["review"] is False
    assert p["caption_en"] == "new"
    assert p["hashtags"] == "#yaml"           # untouched keys survive
    assert REVIEW_POST["review"] is True      # input not mutated


def test_apply_ignores_unknown_keys():
    p = overrides.apply(REVIEW_POST, {"p1": {"platforms": ["tiktok"], "id": "hijack"}})
    assert p["platforms"] == ["instagram"]
    assert p["id"] == "p1"


def test_review_post_stays_held_without_override(q):
    sched, sent = q
    assert publish.run() == 0
    assert sent == []


def test_approve_override_releases_post_at_the_new_slot(q):
    sched, sent = q
    sched.write_text(json.dumps({"p1": {"review": False, "date": _DUE_DATE, "time": _DUE_TIME}}))
    publish.run()
    assert len(sent) == 1
    assert state.is_published("p1", "instagram")


def test_approve_without_new_date_keeps_stale_guard(q):
    # Approving must not fire the 10-week-old YAML slot: the staleness guard still applies.
    sched, sent = q
    sched.write_text(json.dumps({"p1": {"review": False}}))
    publish.run()
    assert sent == []


def test_deleted_override_never_publishes(q, capsys):
    sched, sent = q
    sched.write_text(json.dumps({"p1": {"review": False, "deleted": True,
                                        "date": _DUE_DATE, "time": _DUE_TIME}}))
    publish.run()
    assert sent == []
    assert "DELETED p1" in capsys.readouterr().out


def test_caption_and_media_overrides_reach_the_platform(q):
    sched, sent = q
    sched.write_text(json.dumps({"p1": {"review": False, "date": _DUE_DATE, "time": _DUE_TIME,
                                        "caption_en": "edited", "hashtags": "#edited",
                                        "media": ["p1-1.jpg"]}}))
    publish.run()
    (url, cap), = sent
    assert url.endswith("/p1-1.jpg")
    assert cap == "edited\n\n#edited"


def test_build_data_reflects_overrides(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import build_data
    root = tmp_path
    (root / "content" / "state").mkdir(parents=True)
    (root / "content" / "posts.yaml").write_text(yaml.safe_dump({"posts": [dict(REVIEW_POST)]}))
    (root / "content" / "schedule.json").write_text(json.dumps(
        {"p1": {"review": False, "deleted": True, "date": "2026-10-01", "time": "09:00",
                "caption_en": "edited", "media": ["p1-1.jpg"]}}))
    monkeypatch.setattr(build_data, "ROOT", str(root))
    build_data.run()
    row, = json.load(open(root / "docs" / "data.json"))["posts"]
    assert row["review"] is False
    assert row["deleted"] is True
    assert row["date"] == "2026-10-01" and row["time"] == "09:00"
    assert row["caption_en"] == "edited"
    assert row["media"][0].endswith("/p1-1.jpg")
    assert row["thumb"] == "media/p1-1.jpg"
    assert sorted(row["overridden"]) == ["caption_en", "date", "deleted", "media", "review", "time"]


def test_build_data_no_override_file(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import build_data
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "posts.yaml").write_text(yaml.safe_dump({"posts": [dict(REVIEW_POST)]}))
    monkeypatch.setattr(build_data, "ROOT", str(tmp_path))
    build_data.run()
    row, = json.load(open(tmp_path / "docs" / "data.json"))["posts"]
    assert row["deleted"] is False and row["overridden"] == []


def test_build_data_emits_cover_for_reels(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import build_data
    (tmp_path / "content").mkdir()
    reel = dict(REVIEW_POST, type="reel", media=["r.mp4"], cover="r-cover.png")
    (tmp_path / "content" / "posts.yaml").write_text(yaml.safe_dump({"posts": [reel]}))
    monkeypatch.setattr(build_data, "ROOT", str(tmp_path))
    build_data.run()
    row, = json.load(open(tmp_path / "docs" / "data.json"))["posts"]
    assert row["cover"] == "r-cover.png" and row["thumb"] == "media/r-cover.png"
