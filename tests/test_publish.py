import datetime
import importlib
import os
import subprocess
import sys

import pytest
import yaml

from zoneinfo import ZoneInfo

from conftest import ROOT
from publisher import publish, state

# One hour ago: due, and inside the staleness window so it stays eligible.
_DUE = datetime.datetime.now(ZoneInfo("America/New_York")) - datetime.timedelta(hours=1)

POST = {
    "id": "p1",
    "date": _DUE.strftime("%Y-%m-%d"),
    "time": _DUE.strftime("%H:%M"),
    "tz": "America/New_York",
    "platforms": ["instagram", "facebook"],
    "type": "carousel",
    "media": ["a.png"],
    "caption_en": "hi",
}


@pytest.fixture
def queue(tmp_path, monkeypatch):
    posts_file = tmp_path / "posts.yaml"
    posts_file.write_text(yaml.safe_dump({"posts": [dict(POST)]}))
    monkeypatch.setattr(publish, "POSTS_FILE", str(posts_file))
    monkeypatch.setattr(publish, "SCHEDULE_FILE", str(tmp_path / "schedule.json"))
    monkeypatch.setattr(state, "STATE_FILE", str(tmp_path / "published.json"))


def _boom(*args, **kwargs):
    raise RuntimeError("IG API error 190: bad token")


def test_run_returns_zero_when_all_succeed(queue, monkeypatch):
    monkeypatch.setattr(publish.instagram, "publish_single", lambda u, c: {"id": "ig1"})
    monkeypatch.setattr(publish.facebook, "publish_images", lambda u, m: {"id": "fb1"})
    assert publish.run() == 0
    assert state.is_published("p1", "instagram")
    assert state.is_published("p1", "facebook")


def test_failure_is_counted_and_other_platforms_still_publish(queue, monkeypatch, capsys):
    monkeypatch.setattr(publish.instagram, "publish_single", _boom)
    monkeypatch.setattr(publish.facebook, "publish_images", lambda u, m: {"id": "fb1"})
    assert publish.run() == 1
    assert state.is_published("p1", "facebook")       # failure didn't block facebook
    assert not state.is_published("p1", "instagram")  # failed -> retried next run
    assert "FAILED p1 -> instagram" in capsys.readouterr().err


def test_main_exits_nonzero_on_any_failure(queue, monkeypatch):
    monkeypatch.setattr(publish.instagram, "publish_single", _boom)
    monkeypatch.setattr(publish.facebook, "publish_images", lambda u, m: {"id": "fb1"})
    assert publish.main() == 1


def test_main_exits_zero_when_all_succeed(queue, monkeypatch):
    monkeypatch.setattr(publish.instagram, "publish_single", lambda u, c: {"id": "ig1"})
    monkeypatch.setattr(publish.facebook, "publish_images", lambda u, m: {"id": "fb1"})
    assert publish.main() == 0


def test_failed_platform_retries_next_run_without_double_posting(queue, monkeypatch):
    fb_calls = []
    monkeypatch.setattr(publish.facebook, "publish_images",
                        lambda u, m: fb_calls.append(1) or {"id": "fb1"})
    monkeypatch.setattr(publish.instagram, "publish_single", _boom)
    assert publish.run() == 1

    monkeypatch.setattr(publish.instagram, "publish_single", lambda u, c: {"id": "ig1"})
    assert publish.run() == 0
    assert state.is_published("p1", "instagram")  # retried and succeeded
    assert len(fb_calls) == 1                     # facebook not double-posted


def test_paths_are_env_overridable(monkeypatch):
    """Needed so subprocess tests (and local experiments) never touch the real queue."""
    with monkeypatch.context() as m:
        m.setenv("SPRIG_POSTS_FILE", "/x/posts.yaml")
        m.setenv("SPRIG_SCHEDULE_FILE", "/x/schedule.json")
        m.setenv("SPRIG_STATE_FILE", "/x/published.json")
        importlib.reload(publish)
        importlib.reload(state)
        assert publish.POSTS_FILE == "/x/posts.yaml"
        assert publish.SCHEDULE_FILE == "/x/schedule.json"
        assert state.STATE_FILE == "/x/published.json"
    importlib.reload(publish)
    importlib.reload(state)


def _run_module(tmp_path, posts):
    posts_file = tmp_path / "posts.yaml"
    posts_file.write_text(yaml.safe_dump({"posts": posts}))
    env = {
        **os.environ,
        "SPRIG_POSTS_FILE": str(posts_file),
        "SPRIG_SCHEDULE_FILE": str(tmp_path / "schedule.json"),
        "SPRIG_STATE_FILE": str(tmp_path / "published.json"),
    }
    return subprocess.run(
        [sys.executable, "-m", "publisher.publish"],
        env=env, cwd=ROOT, capture_output=True, text=True, timeout=60,
    )


def test_module_exit_code_is_1_when_a_publish_fails(tmp_path):
    # unknown platform -> raises inside the per-platform try, no network involved
    r = _run_module(tmp_path, [{**POST, "platforms": ["bogus"]}])
    assert r.returncode == 1
    assert "FAILED p1 -> bogus" in r.stderr


def test_module_exit_code_is_0_when_nothing_is_due(tmp_path):
    r = _run_module(tmp_path, [{**POST, "date": "2099-01-01"}])
    assert r.returncode == 0


def _queue_with(tmp_path, monkeypatch, **post_overrides):
    posts_file = tmp_path / "posts.yaml"
    posts_file.write_text(yaml.safe_dump({"posts": [{**POST, **post_overrides}]}))
    monkeypatch.setattr(publish, "POSTS_FILE", str(posts_file))
    monkeypatch.setattr(publish, "SCHEDULE_FILE", str(tmp_path / "schedule.json"))
    monkeypatch.setattr(state, "STATE_FILE", str(tmp_path / "published.json"))


def test_stale_post_is_skipped_not_published(tmp_path, monkeypatch, capsys):
    """The June-queue case: a token arriving weeks late must not dump the backlog."""
    _queue_with(tmp_path, monkeypatch, date="2026-06-21", time="12:00")
    monkeypatch.setattr(publish.instagram, "publish_single", _boom)
    monkeypatch.setattr(publish.facebook, "publish_images", _boom)
    assert publish.run() == 0                      # skipped, not failed
    assert not state.is_published("p1", "instagram")
    assert "STALE p1" in capsys.readouterr().out


def test_stale_window_is_configurable(tmp_path, monkeypatch):
    """Raising the window is how you publish a backlog on purpose."""
    _queue_with(tmp_path, monkeypatch, date="2026-06-21", time="12:00")
    monkeypatch.setattr(publish, "MAX_LATE_HOURS", 24 * 365 * 10)
    monkeypatch.setattr(publish.instagram, "publish_single", lambda u, c: {"id": "ig1"})
    monkeypatch.setattr(publish.facebook, "publish_images", lambda u, m: {"id": "fb1"})
    assert publish.run() == 0
    assert state.is_published("p1", "instagram")


def test_future_post_is_not_due(tmp_path, monkeypatch):
    ahead = datetime.datetime.now(ZoneInfo("America/New_York")) + datetime.timedelta(days=1)
    _queue_with(tmp_path, monkeypatch,
                date=ahead.strftime("%Y-%m-%d"), time=ahead.strftime("%H:%M"))
    monkeypatch.setattr(publish.instagram, "publish_single", _boom)
    monkeypatch.setattr(publish.facebook, "publish_images", _boom)
    assert publish.run() == 0
    assert not state.is_published("p1", "instagram")
