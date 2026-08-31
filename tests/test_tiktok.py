import pytest

from conftest import FakeResponse
from publisher import config, tiktok


@pytest.fixture(autouse=True)
def _reset_token_cache(monkeypatch):
    tiktok._access_token_cache = None
    monkeypatch.setattr(config, "TIKTOK_CLIENT_KEY", "ck")
    monkeypatch.setattr(config, "TIKTOK_CLIENT_SECRET", "cs")
    monkeypatch.setattr(config, "TIKTOK_REFRESH_TOKEN", "rt-old")
    monkeypatch.setattr(config, "TIKTOK_MODE", "inbox")
    yield
    tiktok._access_token_cache = None


@pytest.fixture
def tt_api(monkeypatch):
    """Fake TikTok API: records calls, returns canned tokens/upload targets."""
    calls = []

    def fake_post(url, headers=None, data=None, json=None, timeout=None):
        calls.append(("POST", url, data or json))
        if url.endswith("/oauth/token/"):
            return FakeResponse(200, {"access_token": "at-24h", "expires_in": 86400,
                                      "refresh_token": "rt-old", "open_id": "open123"})
        if "/post/publish/" in url:
            return FakeResponse(200, {"data": {"publish_id": "pub42",
                                               "upload_url": "https://up.tiktok/x"},
                                      "error": {"code": "ok"}})
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url, timeout=None):
        calls.append(("GET", url))
        return FakeResponse(200, content=b"\x00" * 1024)

    def fake_put(url, data=None, headers=None, timeout=None):
        calls.append(("PUT", url, headers))
        return FakeResponse(201)

    monkeypatch.setattr(tiktok.requests, "post", fake_post)
    monkeypatch.setattr(tiktok.requests, "get", fake_get)
    monkeypatch.setattr(tiktok.requests, "put", fake_put)
    return calls


def test_inbox_mode_uses_inbox_endpoint_without_caption(tt_api):
    assert tiktok.publish_video("https://x/clip.mp4", "hola") == "pub42"
    init = [c for c in tt_api if c[0] == "POST" and "publish" in c[1]][0]
    assert "inbox/video/init" in init[1]
    assert "post_info" not in init[2]                      # inbox drafts carry no caption
    assert init[2]["source_info"]["video_size"] == 1024


def test_direct_mode_carries_caption_and_privacy(tt_api, monkeypatch):
    monkeypatch.setattr(config, "TIKTOK_MODE", "direct")
    tiktok.publish_video("https://x/clip.mp4", "hola tiktok")
    init = [c for c in tt_api if c[0] == "POST" and "publish" in c[1]][0]
    assert "post/publish/video/init" in init[1]
    assert init[2]["post_info"]["title"] == "hola tiktok"
    assert init[2]["post_info"]["privacy_level"] == "SELF_ONLY"


def test_upload_sends_single_chunk_with_content_range(tt_api):
    tiktok.publish_video("https://x/clip.mp4", "hola")
    put = [c for c in tt_api if c[0] == "PUT"][0]
    assert put[2]["Content-Range"] == "bytes 0-1023/1024"


def test_token_refresh_happens_once_per_run(tt_api):
    tiktok.publish_video("https://x/a.mp4", "a")
    tiktok.publish_video("https://x/b.mp4", "b")
    refreshes = [c for c in tt_api if c[0] == "POST" and c[1].endswith("/oauth/token/")]
    assert len(refreshes) == 1


def test_rotated_refresh_token_prints_loud_warning(tt_api, monkeypatch, capsys):
    def rotating_post(url, headers=None, data=None, json=None, timeout=None):
        if url.endswith("/oauth/token/"):
            return FakeResponse(200, {"access_token": "at", "refresh_token": "rt-NEW-9zzzzzzz"})
        return FakeResponse(200, {"data": {"publish_id": "p", "upload_url": "https://u/x"},
                                  "error": {"code": "ok"}})
    monkeypatch.setattr(tiktok.requests, "post", rotating_post)
    tiktok.publish_video("https://x/clip.mp4", "hola")
    assert "ROTATED" in capsys.readouterr().err


def test_missing_config_raises_before_any_call(monkeypatch):
    monkeypatch.setattr(config, "TIKTOK_REFRESH_TOKEN", "")
    with pytest.raises(RuntimeError, match="TIKTOK_CLIENT_KEY"):
        tiktok.publish_video("https://x/clip.mp4", "hola")


def test_api_error_body_is_surfaced(monkeypatch):
    body = {"error": {"code": "access_token_invalid", "message": "The access token is invalid",
                      "log_id": "L1"}}
    monkeypatch.setattr(tiktok.requests, "post", lambda *a, **k: FakeResponse(401, body))
    with pytest.raises(RuntimeError) as exc:
        tiktok._access_token()
    assert "access_token_invalid" in str(exc.value)


def test_zero_byte_media_refuses_to_upload(tt_api, monkeypatch):
    monkeypatch.setattr(tiktok.requests, "get", lambda *a, **k: FakeResponse(200, content=b""))
    with pytest.raises(RuntimeError, match="0 bytes"):
        tiktok.publish_video("https://x/clip.mp4", "hola")


def test_non_reel_on_tiktok_raises():
    from publisher import publish
    post = {"id": "p1", "type": "carousel", "caption_en": "hi"}
    with pytest.raises(RuntimeError, match="video-only"):
        publish._publish_one("tiktok", post, ["https://x/img.png"], "hi")
