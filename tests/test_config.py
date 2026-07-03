import importlib

from publisher import config


def _reload_with(monkeypatch, **env):
    with monkeypatch.context() as m:
        for k in ("IG_ACCESS_TOKEN", "IG_API_BASE", "META_ACCESS_TOKEN"):
            m.delenv(k, raising=False)
        for k, v in env.items():
            m.setenv(k, v)
        cfg = importlib.reload(config)
        yield cfg
    importlib.reload(config)  # restore real env values for other tests


def test_direct_login_token_switches_to_instagram_graph(monkeypatch):
    for cfg in _reload_with(monkeypatch, IG_ACCESS_TOKEN="ig-token"):
        assert cfg.IG_TOKEN == "ig-token"
        assert "graph.instagram.com" in cfg.IG_GRAPH


def test_without_direct_login_falls_back_to_page_token(monkeypatch):
    for cfg in _reload_with(monkeypatch, META_ACCESS_TOKEN="page-token"):
        assert cfg.IG_TOKEN == "page-token"
        assert cfg.IG_GRAPH == cfg.GRAPH


def test_ig_api_base_env_overrides(monkeypatch):
    for cfg in _reload_with(monkeypatch, IG_ACCESS_TOKEN="t", IG_API_BASE="https://graph.example.com/v99.0"):
        assert cfg.IG_GRAPH == "https://graph.example.com/v99.0"
