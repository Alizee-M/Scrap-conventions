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


def test_test_alert_route_404s_without_password_configured(client, monkeypatch):
    monkeypatch.delenv("ALERT_TEST_PASSWORD", raising=False)

    resp = client.post("/api/test-alert", headers={"X-Test-Password": "anything"})

    assert resp.status_code == 404


def test_test_alert_route_404s_with_wrong_password(client, monkeypatch):
    monkeypatch.setenv("ALERT_TEST_PASSWORD", "correct-horse")

    resp = client.post("/api/test-alert", headers={"X-Test-Password": "wrong"})

    assert resp.status_code == 404


def test_test_alert_route_sends_notification_with_correct_password(client, monkeypatch):
    monkeypatch.setenv("ALERT_TEST_PASSWORD", "correct-horse")

    import alerts
    monkeypatch.setattr(alerts, "send_test_notification", lambda: True)

    resp = client.post("/api/test-alert", headers={"X-Test-Password": "correct-horse"})

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_test_alert_route_reports_failure_when_webhook_not_configured(client, monkeypatch):
    monkeypatch.setenv("ALERT_TEST_PASSWORD", "correct-horse")

    import alerts
    monkeypatch.setattr(alerts, "send_test_notification", lambda: False)

    resp = client.post("/api/test-alert", headers={"X-Test-Password": "correct-horse"})

    assert resp.status_code == 500
