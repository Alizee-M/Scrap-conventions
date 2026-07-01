import pytest

import app as app_module


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "_last_manual_refresh", 0.0)
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_refresh_succeeds_then_gets_rate_limited(client, monkeypatch):
    calls = []

    def fake_get_conventions(force_refresh=False):
        calls.append(force_refresh)
        return [{"name": "Con"}]

    monkeypatch.setattr(app_module, "get_conventions", fake_get_conventions)

    first = client.post("/api/refresh")
    assert first.status_code == 200
    assert first.get_json()["count"] == 1

    second = client.post("/api/refresh")
    assert second.status_code == 429
    assert "retry_after" in second.get_json()

    # The second call must not have triggered another scrape.
    assert calls == [True]


def test_refresh_allowed_again_after_cooldown_elapses(client, monkeypatch):
    def fake_get_conventions(force_refresh=False):
        return [{"name": "Con"}]

    monkeypatch.setattr(app_module, "get_conventions", fake_get_conventions)
    monkeypatch.setattr(app_module, "REFRESH_COOLDOWN_SECONDS", 0)

    first = client.post("/api/refresh")
    assert first.status_code == 200

    second = client.post("/api/refresh")
    assert second.status_code == 200
