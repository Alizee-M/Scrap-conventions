import json
import logging
import os

import requests

from geocoder import geocode, haversine
from settings_store import load_config

logger = logging.getLogger(__name__)

SEEN_FILE = "cache/alerted_events.json"
SOURCE_STATE_FILE = "cache/source_alert_state.json"

SOURCE_NAMES = {
    "lagendageek": "L'Agenda Geek",
    "romgame": "Rom-Game",
    "bede": "Bédé.fr",
}


def _event_key(event: dict) -> str:
    return f"{event['name'].strip().lower()}|{event.get('date')}"


def _load_seen() -> set[str]:
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))


def _save_seen(keys: set[str]):
    os.makedirs("cache", exist_ok=True)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(keys), f, ensure_ascii=False, indent=2)


def _post_discord_message(webhook_url: str, content: str) -> bool:
    try:
        resp = requests.post(webhook_url, json={"content": content}, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error(f"Discord webhook failed: {e}")
        return False


def _send_discord(webhook_url: str, event: dict):
    lines = [f"**Nouvelle convention : {event['name']}**"]
    if event.get("date"):
        lines.append(f"Date : {event['date']}")
    if event.get("location"):
        lines.append(f"Lieu : {event['location']}")
    if event.get("url"):
        lines.append(event["url"])
    _post_discord_message(webhook_url, "\n".join(lines))


def send_test_notification() -> bool:
    """Sends a fixed test message straight to the webhook, bypassing the
    new-event/seen-file logic — used by the hidden /api/test-alert route to
    verify the configured webhook is valid without waiting for a real scrape."""
    webhook_url = load_config()["discord_webhook_url"]
    if not webhook_url:
        return False
    return _post_discord_message(webhook_url, "🔔 Test Scrap-Conventions : le webhook Discord fonctionne !")


def check_and_notify(events: list[dict]) -> None:
    """Alert (via Discord webhook) on newly-scraped conventions within
    alert_radius_km of alert_city, as configured on /settings. Reads config
    from disk at call time so a config change via the settings page takes
    effect on the very next scrape without a restart.

    First call ever (no SEEN_FILE yet) bootstraps the seen-set without
    alerting — otherwise enabling this on an app that already has a full
    cache would blast a notification for every existing upcoming event.
    """
    config = load_config()
    webhook_url = config["discord_webhook_url"]
    if not webhook_url:
        return

    alert_city = config["alert_city"]
    radius_km = float(config["alert_radius_km"] or 50)

    first_run = not os.path.exists(SEEN_FILE)
    seen = _load_seen()
    center = geocode(alert_city) if alert_city else None

    new_keys = set()
    for event in events:
        key = _event_key(event)
        if key in seen:
            continue
        new_keys.add(key)

        if first_run:
            continue

        if center:
            if not (event.get("lat") and event.get("lon")):
                continue  # can't confirm distance without coordinates — skip
            if haversine(center[0], center[1], event["lat"], event["lon"]) > radius_km:
                continue

        _send_discord(webhook_url, event)

    _save_seen(seen | new_keys)


def _load_source_state() -> dict:
    if not os.path.exists(SOURCE_STATE_FILE):
        return {}
    with open(SOURCE_STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_source_state(state: dict) -> None:
    os.makedirs("cache", exist_ok=True)
    with open(SOURCE_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def check_source_health(health: dict) -> None:
    """Alerts (via Discord) when a source flips from OK to broken (0 events
    or a scrape error) or back to OK — only on the flip, not on every scrape
    while it stays in the same state, so an already-known-broken source
    doesn't spam a message once a day."""
    webhook_url = load_config()["discord_webhook_url"]
    if not webhook_url:
        return

    previous_state = _load_source_state()
    new_state = {}

    for key, h in health.items():
        is_broken = h["count"] == 0 or h["error"] is not None
        new_state[key] = is_broken
        was_broken = previous_state.get(key, False)
        name = SOURCE_NAMES.get(key, key)

        if is_broken and not was_broken:
            reason = h["error"] or "0 événement récupéré"
            _post_discord_message(
                webhook_url,
                f"⚠️ Source cassée : **{name}** ({reason}) — le scraper doit probablement être corrigé.",
            )
        elif was_broken and not is_broken:
            _post_discord_message(webhook_url, f"✅ Source rétablie : **{name}** ({h['count']} événements).")

    _save_source_state(new_state)
