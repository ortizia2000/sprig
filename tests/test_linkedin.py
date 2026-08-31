import pytest

from conftest import FakeResponse
from publisher import config, linkedin


@pytest.fixture(autouse=True)
def _reset_author_cache():
    linkedin._author_cache = None
    yield
    linkedin._author_cache = None


@pytest.fixture
def li_api(monkeypatch):
    """Fake LinkedIn API: records every call, returns canned urns/ids."""
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(("GET", url))
        if url.endswith("/userinfo"):
            return FakeResponse(200, {"sub": "MEMBER99", "name": "Nelly Ortiz"})
        return FakeResponse(200, {})  # media byte fetch

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(("POST", url, json))
        if "initializeUpload" in url:
            return FakeResponse(200, {"value": {"uploadUrl": "https://up/x",
                                                "image": "urn:li:image:IMG1"}})
        return FakeResponse(201, {}, {"x-restli-id": "urn:li:share:S1"})

    monkeypatch.setattr(linkedin.requests, "get", fake_get)
    monkeypatch.setattr(linkedin.requests, "post", fake_post)
    monkeypatch.setattr(linkedin.requests, "put",
                        lambda *a, **k: FakeResponse(201))
    monkeypatch.setattr(config, "LINKEDIN_TOKEN", "tok")
    return calls


def test_posts_as_member_when_no_org_id(li_api, monkeypatch):
    """The mode that actually works today: w_member_social, author = the person."""
    monkeypatch.setattr(config, "LINKEDIN_ORG_ID", "")
    monkeypatch.setattr(config, "LINKEDIN_MEMBER_ID", "")
    assert linkedin.publish_image("https://x/img.png", "hola") == "urn:li:share:S1"
    body = [c for c in li_api if c[0] == "POST" and c[1].endswith("/posts")][0][2]
    assert body["author"] == "urn:li:person:MEMBER99"
    assert body["commentary"] == "hola"


def test_member_id_skips_the_userinfo_lookup(li_api, monkeypatch):
    monkeypatch.setattr(config, "LINKEDIN_ORG_ID", "")
    monkeypatch.setattr(config, "LINKEDIN_MEMBER_ID", "PRESET")
    linkedin.publish_image("https://x/img.png", "hola")
    assert not [c for c in li_api if c[1].endswith("/userinfo")]


def test_org_id_wins_when_set(li_api, monkeypatch):
    monkeypatch.setattr(config, "LINKEDIN_ORG_ID", "12345")
    monkeypatch.setattr(config, "LINKEDIN_MEMBER_ID", "PRESET")
    linkedin.publish_image("https://x/img.png", "hola")
    body = [c for c in li_api if c[0] == "POST" and c[1].endswith("/posts")][0][2]
    assert body["author"] == "urn:li:organization:12345"


def test_missing_token_raises_before_any_call(monkeypatch):
    monkeypatch.setattr(config, "LINKEDIN_TOKEN", "")
    with pytest.raises(RuntimeError, match="LINKEDIN_ACCESS_TOKEN"):
        linkedin.publish_image("https://x/img.png", "hola")


def test_api_error_body_is_surfaced(monkeypatch):
    monkeypatch.setattr(config, "LINKEDIN_TOKEN", "tok")
    monkeypatch.setattr(config, "LINKEDIN_ORG_ID", "12345")
    monkeypatch.setattr(linkedin.requests, "post", lambda *a, **k: FakeResponse(
        403, {"message": "Not enough permissions to access: POST /posts",
              "serviceErrorCode": 100}))
    with pytest.raises(RuntimeError) as exc:
        linkedin.publish_image("https://x/img.png", "hola")
    assert "Not enough permissions" in str(exc.value)


def test_reel_on_linkedin_raises_instead_of_uploading_mp4_as_an_image():
    from publisher import publish
    post = {"id": "p1", "type": "reel", "caption_en": "hi"}
    with pytest.raises(RuntimeError, match="video posting not supported"):
        publish._publish_one("linkedin", post, ["https://x/clip.mp4"], "hi")
