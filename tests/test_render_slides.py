"""tools/render_slides.py — HTML slides -> JPEG via headless Chrome, idempotent
through a per-set manifest of source hashes (so an unchanged set is never
re-rendered on a different machine and silently swapped under a live post)."""
import io
import json
import os
import stat
import subprocess
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, os.path.join(ROOT, "tools"))
import render_slides  # noqa: E402


def _png_bytes(w=216, h=270):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 15, 17)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A fake repo with one slide set and a fake Chrome that writes a PNG and
    logs every invocation."""
    slides = tmp_path / "slides" / "demo"
    slides.mkdir(parents=True)
    (slides / "tpl.css").write_text("body{background:#000}")
    for n in (1, 2, 10):  # 10 last: numeric order, not lexical
        (slides / f"s{n}.html").write_text(f"<html><body>{n}</body></html>")
    (tmp_path / "docs" / "media").mkdir(parents=True)
    (tmp_path / "content" / "media").mkdir(parents=True)
    png = tmp_path / "fixture.png"
    png.write_bytes(_png_bytes())
    log = tmp_path / "chrome.log"
    chrome = tmp_path / "chrome"
    chrome.write_text(
        "#!/bin/sh\n"
        f"echo \"$@\" >> '{log}'\n"
        "for a in \"$@\"; do case \"$a\" in --screenshot=*) out=\"${a#--screenshot=}\";; esac; done\n"
        f"cp '{png}' \"$out\"\n")
    chrome.chmod(chrome.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CHROME", str(chrome))
    monkeypatch.setattr(render_slides, "ROOT", str(tmp_path))
    return tmp_path, log


def _calls(log):
    return log.read_text().splitlines() if log.exists() else []


def test_renders_in_numeric_order_to_both_media_dirs(repo):
    root, log = repo
    assert render_slides.main([]) == 0
    from PIL import Image
    for n in (1, 2, 3):
        for d in ("docs", "content"):
            p = root / d / "media" / f"demo-{n}.jpg"
            assert p.exists(), p
            assert Image.open(p).format == "JPEG"
            assert Image.open(p).size == (1440, 1800)
    calls = _calls(log)
    assert len(calls) == 3
    assert calls[0].endswith("s1.html") and calls[1].endswith("s2.html") and calls[2].endswith("s10.html")
    assert "--window-size=1080,1350" in calls[0]
    assert "--force-device-scale-factor=2" in calls[0]
    man = json.load(open(root / "slides" / "demo" / "manifest.json"))
    assert man["outputs"] == ["demo-1.jpg", "demo-2.jpg", "demo-3.jpg"]
    assert len(man["sha256"]) == 64


def test_unchanged_set_is_skipped(repo, capsys):
    root, log = repo
    render_slides.main([])
    n = len(_calls(log))
    assert render_slides.main([]) == 0
    assert len(_calls(log)) == n            # no new Chrome calls
    assert "SKIP demo" in capsys.readouterr().out


def test_source_change_and_force_rerender(repo):
    root, log = repo
    render_slides.main([])
    n = len(_calls(log))
    (root / "slides" / "demo" / "tpl.css").write_text("body{background:#fff}")
    render_slides.main([])
    assert len(_calls(log)) == n + 3
    render_slides.main(["--force"])
    assert len(_calls(log)) == n + 6


def test_only_named_sets_render(repo):
    root, log = repo
    other = root / "slides" / "other"
    other.mkdir()
    (other / "s1.html").write_text("<html/>")
    assert render_slides.main(["demo"]) == 0
    assert not (root / "docs" / "media" / "other-1.jpg").exists()
    assert render_slides.main(["nope"]) == 1  # unknown set is an error, not a silent no-op


def test_check_mode_reports_without_rendering(repo, capsys):
    root, log = repo
    assert render_slides.main(["--check"]) == 0
    assert _calls(log) == []
    assert "STALE demo" in capsys.readouterr().out
    assert not (root / "docs" / "media" / "demo-1.jpg").exists()


def test_missing_chrome_is_a_loud_failure(repo, monkeypatch, capsys):
    monkeypatch.setenv("CHROME", "/nonexistent/chrome")
    monkeypatch.setattr(render_slides, "CHROME_CANDIDATES", [])
    assert render_slides.main([]) == 2
    assert "Chrome" in capsys.readouterr().err


def test_chrome_producing_no_file_fails_that_slide(repo, capsys):
    root, log = repo
    (root / "chrome").write_text("#!/bin/sh\nexit 0\n")
    assert render_slides.main([]) == 1
    assert "FAIL demo s1.html" in capsys.readouterr().err
    assert not (root / "slides" / "demo" / "manifest.json").exists()  # nothing recorded as done


def test_record_pins_manifest_without_rendering(repo, capsys):
    root, log = repo
    # outputs must already exist for --record, else it refuses
    assert render_slides.main(["--record", "demo"]) == 1
    assert "outputs missing" in capsys.readouterr().err
    for n in (1, 2, 3):
        for d in ("docs", "content"):
            (root / d / "media" / f"demo-{n}.jpg").write_bytes(b"jpeg")
    assert render_slides.main(["--record", "demo"]) == 0
    assert _calls(log) == []
    man = json.load(open(root / "slides" / "demo" / "manifest.json"))
    assert man["outputs"] == ["demo-1.jpg", "demo-2.jpg", "demo-3.jpg"]
    # and the set is now FRESH: a plain run skips it
    render_slides.main([])
    assert _calls(log) == []
