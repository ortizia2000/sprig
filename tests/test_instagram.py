import pytest

from conftest import FakeResponse
from publisher import instagram


@pytest.fixture
def fake_api(monkeypatch):
    """Fake Graph API: records the order of calls, returns canned ids/statuses."""
    calls = []
    child_count = {"n": 0}

    def fake_post(url, data=None, timeout=None):
        if url.endswith("/media_publish"):
            calls.append("publish")
            return FakeResponse(200, {"id": "media123"})
        if data.get("media_type") == "CAROUSEL":
            calls.append("create_carousel")
            return FakeResponse(200, {"id": "carousel1"})
        child_count["n"] += 1
        calls.append(f"create_child{child_count['n']}")
        return FakeResponse(200, {"id": f"child{child_count['n']}"})

    def fake_get(url, params=None, timeout=None):
        cid = url.rstrip("/").split("/")[-1]
        calls.append(f"status:{cid}")
        return FakeResponse(200, {"status_code": "FINISHED"})

    monkeypatch.setattr(instagram.requests, "post", fake_post)
    monkeypatch.setattr(instagram.requests, "get", fake_get)
    return calls


def test_meta_error_body_is_surfaced(monkeypatch):
    body = {"error": {"message": "Subject must be a business account", "code": 100,
                      "error_subcode": 2207050, "fbtrace_id": "AbCdEf123"}}
    monkeypatch.setattr(instagram.requests, "post", lambda *a, **k: FakeResponse(400, body))
    with pytest.raises(RuntimeError) as exc:
        instagram.publish_single("https://x/img.png", "caption")
    assert "Subject must be a business account" in str(exc.value)
    assert "AbCdEf123" in str(exc.value)


def test_carousel_waits_for_each_child_before_creating_carousel(fake_api):
    resp = instagram.publish_carousel(["https://x/1.png", "https://x/2.png"], "caption")
    assert resp["id"] == "media123"
    before_carousel = fake_api[: fake_api.index("create_carousel")]
    assert "status:child1" in before_carousel
    assert "status:child2" in before_carousel


def test_expired_container_raises_immediately(monkeypatch):
    monkeypatch.setattr(
        instagram.requests, "get",
        lambda *a, **k: FakeResponse(200, {"status_code": "EXPIRED"}),
    )
    with pytest.raises(RuntimeError, match="EXPIRED"):
        instagram._wait_ready("cid1", tries=3, delay=0)


def test_carousel_rejects_more_than_ten_slides(fake_api):
    with pytest.raises(ValueError):
        instagram.publish_carousel([f"https://x/{i}.png" for i in range(11)], "caption")
    assert fake_api == []  # rejected before any API call
