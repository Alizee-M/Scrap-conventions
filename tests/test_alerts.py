import json

import alerts


def _event(name="Japan Tours Festival", event_date="2026-09-01", lat=None, lon=None):
    return {
        "name": name, "date": event_date, "location": "Tours",
        "url": "https://example.com/x", "image": "", "source": "lagendageek",
        "lat": lat, "lon": lon,
    }


def test_no_webhook_configured_does_nothing(tmp_path, monkeypatch):
    seen_file = tmp_path / "alerted.json"
    monkeypatch.setattr(alerts, "SEEN_FILE", str(seen_file))
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

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
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    monkeypatch.delenv("ALERT_CITY", raising=False)

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
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    monkeypatch.setenv("ALERT_CITY", "Tours")
    monkeypatch.setenv("ALERT_RADIUS_KM", "50")

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
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    monkeypatch.setenv("ALERT_CITY", "Tours")
    monkeypatch.setenv("ALERT_RADIUS_KM", "50")

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
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    monkeypatch.delenv("ALERT_CITY", raising=False)

    posted = []
    monkeypatch.setattr(alerts.requests, "post", lambda *a, **k: posted.append(a))

    alerts.check_and_notify([_event(name="New Con Nearby")])

    assert posted == []


def test_event_missing_coordinates_is_skipped_when_center_configured(tmp_path, monkeypatch):
    seen_file = tmp_path / "alerted.json"
    seen_file.write_text(json.dumps([]))
    monkeypatch.setattr(alerts, "SEEN_FILE", str(seen_file))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    monkeypatch.setenv("ALERT_CITY", "Tours")

    monkeypatch.setattr(alerts, "geocode", lambda city: (47.39, 0.68))

    posted = []
    monkeypatch.setattr(alerts.requests, "post", lambda *a, **k: posted.append(a))

    alerts.check_and_notify([_event(name="No Coords Con", lat=None, lon=None)])

    assert posted == []
