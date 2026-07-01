import json

import alerts


def _event(name="Japan Tours Festival", event_date="2026-09-01", lat=None, lon=None):
    return {
        "name": name, "date": event_date, "location": "Tours",
        "url": "https://example.com/x", "image": "", "source": "lagendageek",
        "lat": lat, "lon": lon,
    }


def _config(webhook="", city="", radius=50):
    return {"discord_webhook_url": webhook, "alert_city": city, "alert_radius_km": radius}


def test_send_test_notification_without_webhook_returns_false(monkeypatch):
    monkeypatch.setattr(alerts, "load_config", lambda: _config())

    assert alerts.send_test_notification() is False


def test_send_test_notification_posts_to_webhook(monkeypatch):
    monkeypatch.setattr(alerts, "load_config", lambda: _config(webhook="https://discord.example/webhook"))

    posted = []

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        posted.append((url, json))
        return FakeResp()

    monkeypatch.setattr(alerts.requests, "post", fake_post)

    assert alerts.send_test_notification() is True
    assert posted[0][0] == "https://discord.example/webhook"
    assert "Test" in posted[0][1]["content"]


def test_no_webhook_configured_does_nothing(tmp_path, monkeypatch):
    seen_file = tmp_path / "alerted.json"
    monkeypatch.setattr(alerts, "SEEN_FILE", str(seen_file))
    monkeypatch.setattr(alerts, "load_config", lambda: _config())

    calls = []
    monkeypatch.setattr(alerts.requests, "post", lambda *a, **k: calls.append(a))

    alerts.check_and_notify([_event()])

    assert calls == []
    assert not seen_file.exists()


def test_first_run_bootstraps_without_alerting(tmp_path, monkeypatch):
    """A fresh deploy of this feature on an app that already has cached
    conventions must not blast a notification for every existing event."""
    seen_file = tmp_path / "alerted.json"
    monkeypatch.setattr(alerts, "SEEN_FILE", str(seen_file))
    monkeypatch.setattr(alerts, "load_config", lambda: _config(webhook="https://discord.example/webhook"))

    calls = []
    monkeypatch.setattr(alerts.requests, "post", lambda *a, **k: calls.append(a))

    alerts.check_and_notify([_event(), _event(name="Other Con")])

    assert calls == []
    assert seen_file.exists()
    saved = json.loads(seen_file.read_text())
    assert len(saved) == 2


def test_new_event_within_radius_triggers_discord_post(tmp_path, monkeypatch):
    seen_file = tmp_path / "alerted.json"
    seen_file.write_text(json.dumps(["existing con|2026-01-01"]))
    monkeypatch.setattr(alerts, "SEEN_FILE", str(seen_file))
    monkeypatch.setattr(alerts, "load_config", lambda: _config(webhook="https://discord.example/webhook", city="Tours", radius=50))

    monkeypatch.setattr(alerts, "geocode", lambda city: (47.39, 0.68))
    monkeypatch.setattr(alerts, "haversine", lambda *a: 10.0)

    posted = []

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        posted.append((url, json))
        return FakeResp()

    monkeypatch.setattr(alerts.requests, "post", fake_post)

    alerts.check_and_notify([_event(name="New Con Nearby", lat=47.39, lon=0.68)])

    assert len(posted) == 1
    assert "New Con Nearby" in posted[0][1]["content"]
    saved = json.loads(seen_file.read_text())
    assert "new con nearby|2026-09-01" in saved


def test_new_event_outside_radius_is_not_alerted_but_marked_seen(tmp_path, monkeypatch):
    seen_file = tmp_path / "alerted.json"
    seen_file.write_text(json.dumps([]))
    monkeypatch.setattr(alerts, "SEEN_FILE", str(seen_file))
    monkeypatch.setattr(alerts, "load_config", lambda: _config(webhook="https://discord.example/webhook", city="Tours", radius=50))

    monkeypatch.setattr(alerts, "geocode", lambda city: (47.39, 0.68))
    monkeypatch.setattr(alerts, "haversine", lambda *a: 500.0)

    posted = []
    monkeypatch.setattr(alerts.requests, "post", lambda *a, **k: posted.append(a))

    alerts.check_and_notify([_event(name="Far Away Con", lat=43.6, lon=1.4)])

    assert posted == []
    saved = json.loads(seen_file.read_text())
    assert "far away con|2026-09-01" in saved


def test_already_seen_event_is_not_alerted_again(tmp_path, monkeypatch):
    seen_file = tmp_path / "alerted.json"
    seen_file.write_text(json.dumps(["new con nearby|2026-09-01"]))
    monkeypatch.setattr(alerts, "SEEN_FILE", str(seen_file))
    monkeypatch.setattr(alerts, "load_config", lambda: _config(webhook="https://discord.example/webhook"))

    posted = []
    monkeypatch.setattr(alerts.requests, "post", lambda *a, **k: posted.append(a))

    alerts.check_and_notify([_event(name="New Con Nearby")])

    assert posted == []


def test_event_missing_coordinates_is_skipped_when_center_configured(tmp_path, monkeypatch):
    seen_file = tmp_path / "alerted.json"
    seen_file.write_text(json.dumps([]))
    monkeypatch.setattr(alerts, "SEEN_FILE", str(seen_file))
    monkeypatch.setattr(alerts, "load_config", lambda: _config(webhook="https://discord.example/webhook", city="Tours"))

    monkeypatch.setattr(alerts, "geocode", lambda city: (47.39, 0.68))

    posted = []
    monkeypatch.setattr(alerts.requests, "post", lambda *a, **k: posted.append(a))

    alerts.check_and_notify([_event(name="No Coords Con", lat=None, lon=None)])

    assert posted == []


def _health(count=10, error=None):
    return {"count": count, "scraped_at": "2026-01-01T00:00:00", "error": error}


def test_check_source_health_does_nothing_without_webhook(tmp_path, monkeypatch):
    state_file = tmp_path / "source_state.json"
    monkeypatch.setattr(alerts, "SOURCE_STATE_FILE", str(state_file))
    monkeypatch.setattr(alerts, "load_config", lambda: _config())

    posted = []
    monkeypatch.setattr(alerts.requests, "post", lambda *a, **k: posted.append(a))

    alerts.check_source_health({"bede": _health(count=0)})

    assert posted == []
    assert not state_file.exists()


def test_check_source_health_alerts_when_newly_broken(tmp_path, monkeypatch):
    state_file = tmp_path / "source_state.json"
    monkeypatch.setattr(alerts, "SOURCE_STATE_FILE", str(state_file))
    monkeypatch.setattr(alerts, "load_config", lambda: _config(webhook="https://discord.example/webhook"))

    posted = []

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        posted.append(json["content"])
        return FakeResp()

    monkeypatch.setattr(alerts.requests, "post", fake_post)

    alerts.check_source_health({"bede": _health(count=0)})

    assert len(posted) == 1
    assert "cassée" in posted[0]
    assert "Bédé.fr" in posted[0]
    assert json.loads(state_file.read_text()) == {"bede": True}


def test_check_source_health_does_not_repeat_alert_while_still_broken(tmp_path, monkeypatch):
    state_file = tmp_path / "source_state.json"
    state_file.write_text(json.dumps({"bede": True}))
    monkeypatch.setattr(alerts, "SOURCE_STATE_FILE", str(state_file))
    monkeypatch.setattr(alerts, "load_config", lambda: _config(webhook="https://discord.example/webhook"))

    posted = []
    monkeypatch.setattr(alerts.requests, "post", lambda *a, **k: posted.append(a))

    alerts.check_source_health({"bede": _health(count=0)})

    assert posted == []


def test_check_source_health_alerts_on_recovery(tmp_path, monkeypatch):
    state_file = tmp_path / "source_state.json"
    state_file.write_text(json.dumps({"bede": True}))
    monkeypatch.setattr(alerts, "SOURCE_STATE_FILE", str(state_file))
    monkeypatch.setattr(alerts, "load_config", lambda: _config(webhook="https://discord.example/webhook"))

    posted = []

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        posted.append(json["content"])
        return FakeResp()

    monkeypatch.setattr(alerts.requests, "post", fake_post)

    alerts.check_source_health({"bede": _health(count=15)})

    assert len(posted) == 1
    assert "rétablie" in posted[0]
    assert json.loads(state_file.read_text()) == {"bede": False}


def test_check_source_health_alerts_on_scraper_error_even_with_nonzero_count(tmp_path, monkeypatch):
    state_file = tmp_path / "source_state.json"
    monkeypatch.setattr(alerts, "SOURCE_STATE_FILE", str(state_file))
    monkeypatch.setattr(alerts, "load_config", lambda: _config(webhook="https://discord.example/webhook"))

    posted = []

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        posted.append(json["content"])
        return FakeResp()

    monkeypatch.setattr(alerts.requests, "post", fake_post)

    alerts.check_source_health({"romgame": _health(count=3, error="timeout")})

    assert len(posted) == 1
    assert "timeout" in posted[0]
