import check_auth
from conftest import FakeResponse

from publisher import config


def _ig_env(monkeypatch):
    monkeypatch.setattr(config, "IG_TOKEN", "tok", raising=False)
    monkeypatch.setattr(config, "IG_USER_ID", "17841400000000000")
    monkeypatch.setattr(config, "IG_GRAPH", "https://graph.test/v22.0", raising=False)


def test_check_instagram_ok(monkeypatch, capsys):
    _ig_env(monkeypatch)
    monkeypatch.setattr(
        check_auth.requests, "get",
        lambda *a, **k: FakeResponse(200, {"username": "myceliumai.co", "id": "1"}),
    )
    assert check_auth.check_instagram() is True
    assert "myceliumai.co" in capsys.readouterr().out


def test_check_instagram_bad_token(monkeypatch):
    _ig_env(monkeypatch)
    body = {"error": {"message": "Invalid OAuth access token", "code": 190}}
    monkeypatch.setattr(check_auth.requests, "get", lambda *a, **k: FakeResponse(401, body))
    assert check_auth.check_instagram() is False


def test_check_instagram_skips_when_unconfigured(monkeypatch):
    monkeypatch.setattr(config, "IG_TOKEN", "", raising=False)
    monkeypatch.setattr(config, "IG_USER_ID", "")
    assert check_auth.check_instagram() is None


def test_check_media_ok(monkeypatch):
    monkeypatch.setattr(
        check_auth.requests, "head",
        lambda *a, **k: FakeResponse(200, headers={"Content-Type": "image/png"}),
    )
    assert check_auth.check_media(["https://x/a.png"]) is True


def test_check_media_warns_but_passes_video_served_as_octet_stream(monkeypatch, capsys):
    monkeypatch.setattr(
        check_auth.requests, "head",
        lambda *a, **k: FakeResponse(200, headers={"Content-Type": "application/octet-stream"}),
    )
    assert check_auth.check_media(["https://x/reel.mp4"]) is True
    assert "WARN" in capsys.readouterr().out


def test_check_media_flags_unreachable_or_wrong_type(monkeypatch):
    monkeypatch.setattr(check_auth.requests, "head", lambda *a, **k: FakeResponse(404))
    assert check_auth.check_media(["https://x/missing.png"]) is False

    monkeypatch.setattr(
        check_auth.requests, "head",
        lambda *a, **k: FakeResponse(200, headers={"Content-Type": "text/html"}),
    )
    assert check_auth.check_media(["https://x/a.png"]) is False
