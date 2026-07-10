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


def test_api_conventions_sorts_by_date_by_default(client, monkeypatch):
    convs = [
        {"name": "Late", "date": "2026-09-01", "lat": None, "lon": None},
        {"name": "Early", "date": "2026-08-01", "lat": None, "lon": None},
        {"name": "Undated", "date": None, "lat": None, "lon": None},
    ]
    monkeypatch.setattr(app_module, "get_conventions", lambda: convs)

    resp = client.get("/api/conventions")

    assert resp.status_code == 200
    data = resp.get_json()
    assert [c["name"] for c in data["conventions"]] == ["Early", "Late", "Undated"]
    assert all(c["distance_km"] is None for c in data["conventions"])
    assert data["user_lat"] is None and data["user_lon"] is None


def test_api_conventions_sorts_by_distance_with_lat_lon(client, monkeypatch):
    convs = [
        {"name": "Far", "date": "2026-08-01", "lat": 50.0, "lon": 2.0},
        {"name": "Near", "date": "2026-08-01", "lat": 47.4, "lon": 0.7},
        {"name": "NoCoords", "date": "2026-08-01", "lat": None, "lon": None},
    ]
    monkeypatch.setattr(app_module, "get_conventions", lambda: convs)

    resp = client.get("/api/conventions?sort=distance&lat=47.39&lon=0.68")

    assert resp.status_code == 200
    data = resp.get_json()
    names = [c["name"] for c in data["conventions"]]
    assert names == ["Near", "Far", "NoCoords"]
    assert data["conventions"][0]["distance_km"] < data["conventions"][1]["distance_km"]
    assert data["conventions"][2]["distance_km"] is None
    assert data["user_lat"] == 47.39 and data["user_lon"] == 0.68


def test_api_conventions_geocodes_location_param_when_lat_lon_missing(client, monkeypatch):
    monkeypatch.setattr(app_module, "get_conventions", lambda: [])
    monkeypatch.setattr(app_module, "geocode", lambda loc: (47.39, 0.68) if loc == "Tours" else None)

    resp = client.get("/api/conventions?location=Tours")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["user_lat"] == 47.39 and data["user_lon"] == 0.68


def test_api_conventions_ignores_location_param_when_lat_lon_already_given(client, monkeypatch):
    monkeypatch.setattr(app_module, "get_conventions", lambda: [])

    def fail_geocode(loc):
        raise AssertionError("geocode should not be called when lat/lon are already provided")

    monkeypatch.setattr(app_module, "geocode", fail_geocode)

    resp = client.get("/api/conventions?location=Tours&lat=1.0&lon=2.0")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["user_lat"] == 1.0 and data["user_lon"] == 2.0


def test_api_sources_reports_counts_and_cache_age(client, monkeypatch):
    convs = [
        {"name": "A", "source": "lagendageek"},
        {"name": "B", "source": "lagendageek"},
        {"name": "C", "source": "bede"},
    ]
    monkeypatch.setattr(app_module, "get_conventions", lambda: convs)

    resp = client.get("/api/sources")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_events"] == 3
    by_key = {s["key"]: s for s in data["sources"]}
    assert by_key["lagendageek"]["events"] == 2
    assert by_key["bede"]["events"] == 1
    assert by_key["romgame"]["events"] == 0
    # Blocked/rejected sources are always reported with 0 events regardless of scrape counts.
    assert by_key["nautiljon"]["status"] == "blocked"
    assert by_key["nautiljon"]["events"] == 0


def test_api_sources_flags_warning_when_source_health_reports_broken_scrape(client, monkeypatch):
    monkeypatch.setattr(app_module, "get_conventions", lambda: [])
    monkeypatch.setattr(
        "scraper.load_source_health",
        lambda: {"bede": {"count": 0, "error": "HTTP 500", "scraped_at": "2026-07-10T00:00:00"}},
    )

    resp = client.get("/api/sources")

    assert resp.status_code == 200
    by_key = {s["key"]: s for s in resp.get_json()["sources"]}
    assert by_key["bede"]["warning"] is True
    assert by_key["bede"]["last_scraped_at"] == "2026-07-10T00:00:00"


def test_api_sources_reports_cache_age_when_cache_file_exists(client, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "get_conventions", lambda: [])
    cache_file = tmp_path / "conventions.json"
    cache_file.write_text("[]")
    monkeypatch.setattr("scraper.CACHE_FILE", str(cache_file))

    resp = client.get("/api/sources")

    assert resp.status_code == 200
    assert resp.get_json()["cache_age_seconds"] >= 0


def test_api_refresh_reports_error_when_get_conventions_raises(client, monkeypatch):
    def fail(force_refresh=False):
        raise RuntimeError("scrape boom")

    monkeypatch.setattr(app_module, "get_conventions", fail)

    resp = client.post("/api/refresh")

    assert resp.status_code == 500
    assert "scrape boom" in resp.get_json()["error"]


def test_index_and_static_pages_render(client, monkeypatch):
    monkeypatch.setattr(app_module, "get_conventions", lambda: [])

    assert client.get("/").status_code == 200
    assert client.get("/sources").status_code == 200
    assert client.get("/settings").status_code == 200


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


# ─── background thread targets ──────────────────────────────────────────────
# _background_refresh() runs `while True: sleep(); scrape()`. To test it without
# actually looping forever, time.sleep is faked to raise a sentinel exception
# on its 2nd call, which lets one full iteration run before breaking out.

class _StopLoop(Exception):
    pass


def test_background_refresh_scrapes_once_per_sleep_cycle(monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "get_conventions", lambda force_refresh=False: calls.append(force_refresh))

    sleep_calls = []

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            raise _StopLoop()

    monkeypatch.setattr(app_module.time, "sleep", fake_sleep)

    with pytest.raises(_StopLoop):
        app_module._background_refresh()

    assert sleep_calls == [86400, 86400]
    assert calls == [True]


def test_background_refresh_survives_a_failed_scrape(monkeypatch):
    def fail(force_refresh=False):
        raise RuntimeError("scrape boom")

    monkeypatch.setattr(app_module, "get_conventions", fail)

    sleep_calls = []

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            raise _StopLoop()

    monkeypatch.setattr(app_module.time, "sleep", fake_sleep)

    with pytest.raises(_StopLoop):
        app_module._background_refresh()

    # the loop must reach its 2nd sleep instead of dying on the 1st scrape's exception
    assert sleep_calls == [86400, 86400]


def test_initial_load_runs_to_completion(monkeypatch):
    monkeypatch.setattr(app_module, "get_conventions", lambda: [{"name": "A"}, {"name": "B"}])
    app_module._initial_load()  # no exception = success


def test_initial_load_swallows_scrape_failure(monkeypatch):
    def fail():
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module, "get_conventions", fail)
    app_module._initial_load()  # must not propagate
