import pytest

import app as app_module
import settings_store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "_last_manual_refresh", 0.0)
    monkeypatch.setattr(settings_store, "CONFIG_FILE", str(tmp_path / "config.json"))
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


def test_test_alert_route_404s_when_not_configured(client):
    resp = client.post("/api/test-alert", headers={"X-Settings-Password": "anything"})

    assert resp.status_code == 404


def test_test_alert_route_404s_with_wrong_password(client):
    settings_store.set_up("https://discord.example/webhook", "Tours", 50, "correct-horse")

    resp = client.post("/api/test-alert", headers={"X-Settings-Password": "wrong"})

    assert resp.status_code == 404


def test_test_alert_route_sends_notification_with_correct_password(client, monkeypatch):
    settings_store.set_up("https://discord.example/webhook", "Tours", 50, "correct-horse")

    import alerts
    monkeypatch.setattr(alerts, "send_test_notification", lambda: True)

    resp = client.post("/api/test-alert", headers={"X-Settings-Password": "correct-horse"})

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_test_alert_route_reports_failure_when_webhook_not_configured(client, monkeypatch):
    settings_store.set_up("", "Tours", 50, "correct-horse")

    import alerts
    monkeypatch.setattr(alerts, "send_test_notification", lambda: False)

    resp = client.post("/api/test-alert", headers={"X-Settings-Password": "correct-horse"})

    assert resp.status_code == 500


def test_settings_status_reflects_configuration_state(client):
    assert client.get("/api/settings/status").get_json()["configured"] is False

    settings_store.set_up("https://discord.example/webhook", "Tours", 50, "correct-horse")

    assert client.get("/api/settings/status").get_json()["configured"] is True


def test_settings_setup_then_locked_from_a_second_setup(client):
    resp = client.post("/api/settings/setup", json={
        "discord_webhook_url": "https://discord.example/webhook",
        "alert_city": "Tours",
        "alert_radius_km": 50,
        "password": "secret123",
    })
    assert resp.status_code == 200

    again = client.post("/api/settings/setup", json={
        "discord_webhook_url": "https://evil.example/webhook",
        "alert_city": "Paris",
        "alert_radius_km": 10,
        "password": "hijack",
    })
    assert again.status_code == 409
    assert settings_store.verify_password("secret123") is True


def test_settings_setup_requires_a_password(client):
    resp = client.post("/api/settings/setup", json={
        "discord_webhook_url": "https://discord.example/webhook",
        "alert_city": "Tours",
        "alert_radius_km": 50,
        "password": "",
    })

    assert resp.status_code == 400
    assert settings_store.is_configured() is False


def test_settings_get_requires_correct_password(client):
    settings_store.set_up("https://discord.example/webhook", "Tours", 50, "correct-horse")

    wrong = client.get("/api/settings", headers={"X-Settings-Password": "wrong"})
    assert wrong.status_code == 404

    ok = client.get("/api/settings", headers={"X-Settings-Password": "correct-horse"})
    assert ok.status_code == 200
    data = ok.get_json()
    assert data["discord_webhook_url"] == "https://discord.example/webhook"
    assert data["alert_city"] == "Tours"
    assert "password_hash" not in data


def test_settings_post_updates_values_and_can_rotate_password(client):
    settings_store.set_up("https://discord.example/webhook", "Tours", 50, "correct-horse")

    resp = client.post(
        "/api/settings",
        headers={"X-Settings-Password": "correct-horse"},
        json={
            "discord_webhook_url": "https://discord.example/new-webhook",
            "alert_city": "Paris",
            "alert_radius_km": 20,
            "new_password": "newpass",
        },
    )
    assert resp.status_code == 200

    config = settings_store.load_config()
    assert config["discord_webhook_url"] == "https://discord.example/new-webhook"
    assert config["alert_city"] == "Paris"
    assert config["alert_radius_km"] == 20
    assert settings_store.verify_password("correct-horse") is False
    assert settings_store.verify_password("newpass") is True
