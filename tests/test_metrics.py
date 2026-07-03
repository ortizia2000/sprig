from conftest import FakeResponse

from publisher import config, metrics


def test_ig_insights_use_ig_graph_and_token(monkeypatch):
    monkeypatch.setattr(config, "IG_GRAPH", "https://graph.ig-test/v22.0", raising=False)
    monkeypatch.setattr(config, "IG_TOKEN", "ig-token", raising=False)
    seen = {}

    def fake_get(url, params=None, timeout=None):
        seen["url"] = url
        seen["token"] = params["access_token"]
        return FakeResponse(200, {"data": [{"name": "reach", "values": [{"value": 7}]}]})

    monkeypatch.setattr(metrics.requests, "get", fake_get)
    out = metrics._ig_insights("media123")
    assert out == {"reach": 7}
    assert seen["url"].startswith("https://graph.ig-test/v22.0/")
    assert seen["token"] == "ig-token"
