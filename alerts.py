import json
import logging
import os

import requests

from geocoder import geocode, haversine

logger = logging.getLogger(__name__)

SEEN_FILE = "cache/alerted_events.json"


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


def _send_discord(webhook_url: str, event: dict):
    lines = [f"**Nouvelle convention : {event['name']}**"]
    if event.get("date"):
        lines.append(f"Date : {event['date']}")
    if event.get("location"):
        lines.append(f"Lieu : {event['location']}")
    if event.get("url"):
        lines.append(event["url"])
    try:
        resp = requests.post(webhook_url, json={"content": "\n".join(lines)}, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Discord webhook failed: {e}")


def check_and_notify(events: list[dict]) -> None:
    """Alert (via Discord webhook) on newly-scraped conventions within
    ALERT_RADIUS_KM of ALERT_CITY. Reads config from env vars at call time
    (not import time) so tests/monkeypatch of os.environ are honored, and so
    Portainer env changes take effect on the next scrape without a rebuild.

    First call ever (no SEEN_FILE yet) bootstraps the seen-set without
    alerting — otherwise enabling this on an app that already has a full
    cache would blast a notification for every existing upcoming event.
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        return

    alert_city = os.environ.get("ALERT_CITY", "")
    radius_km = float(os.environ.get("ALERT_RADIUS_KM", "50"))

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
