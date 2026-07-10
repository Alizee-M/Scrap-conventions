import logging
import threading
import time
from flask import Flask, jsonify, render_template, request
from geocoder import geocode, haversine
from scraper import get_conventions
import settings_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

REFRESH_COOLDOWN_SECONDS = 600  # protects the 3 scraped sources from being hammered
_cooldown_lock = threading.Lock()  # guards the check-and-set below, not the scrape itself
_last_manual_refresh = 0.0


def _background_refresh():
    while True:
        time.sleep(86400)
        logger.info("Background refresh triggered")
        try:
            get_conventions(force_refresh=True)
        except Exception as e:
            logger.error(f"Background refresh failed: {e}")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/conventions")
def api_conventions():
    sort = request.args.get("sort", "date")
    user_lat = request.args.get("lat", type=float)
    user_lon = request.args.get("lon", type=float)
    location_name = request.args.get("location", "")

    if location_name and (user_lat is None or user_lon is None):
        coords = geocode(location_name)
        if coords:
            user_lat, user_lon = coords

    convs = get_conventions()

    result = []
    for c in convs:
        entry = dict(c)
        if user_lat is not None and user_lon is not None and c.get("lat") and c.get("lon"):
            entry["distance_km"] = round(haversine(user_lat, user_lon, c["lat"], c["lon"]), 1)
        else:
            entry["distance_km"] = None
        result.append(entry)

    if sort == "distance" and user_lat is not None:
        result.sort(key=lambda x: x["distance_km"] if x["distance_km"] is not None else 99999)
    else:
        result.sort(key=lambda x: x["date"] or "9999")

    return jsonify({"conventions": result, "user_lat": user_lat, "user_lon": user_lon})


@app.route("/sources")
def sources_page():
    return render_template("sources.html")


@app.route("/api/sources")
def api_sources():
    import os
    import time as _time
    from scraper import CACHE_FILE, load_source_health

    convs = get_conventions()

    counts = {}
    for c in convs:
        src = c.get("source", "inconnu")
        counts[src] = counts.get(src, 0) + 1

    # Raw per-source scrape counts (pre-dedup) — a source returning 0 events
    # is a sign it silently broke, even if the dedup-based count above isn't 0.
    health = load_source_health()

    def _active_source(key: str) -> dict:
        h = health.get(key)
        events = h["count"] if h else counts.get(key, 0)
        return {
            "events": events,
            "warning": h is not None and (h["count"] == 0 or h["error"] is not None),
            "last_scraped_at": h["scraped_at"] if h else None,
        }

    cache_age = None
    if os.path.exists(CACHE_FILE):
        cache_age = int(_time.time() - os.stat(CACHE_FILE).st_mtime)

    sources = [
        {
            "name": "L'Agenda Geek",
            "key": "lagendageek",
            "url": "https://lagendageek.com/liste-des-evenements/",
            "description": "Agenda geek France + Belgique + Suisse",
            "status": "active",
            **_active_source("lagendageek"),
        },
        {
            "name": "Rom-Game",
            "key": "romgame",
            "url": "https://www.rom-game.fr/agenda/",
            "description": "Conventions jeux, manga, culture pop (200+ events)",
            "status": "active",
            **_active_source("romgame"),
        },
        {
            "name": "Bédé.fr",
            "key": "bede",
            "url": "https://www.bede.fr/festivals-manga",
            "description": "Festivals manga spécialisés",
            "status": "active",
            **_active_source("bede"),
        },
        {
            "name": "Nautiljon",
            "key": "nautiljon",
            "url": "https://www.nautiljon.com/evenements/",
            "description": "Agenda anime/manga — bloqué (403)",
            "status": "blocked",
            "events": 0,
        },
        {
            "name": "Manga-News",
            "key": "manganews",
            "url": "https://www.manga-news.com/index.php/agenda/",
            "description": "Agenda manga — bloqué (403)",
            "status": "blocked",
            "events": 0,
        },
        {
            "name": "eVous",
            "key": "evous",
            "url": "https://www.evous.fr/agenda-france/calendrier-salons-sci-fi-manga-fantasy-geek.html",
            "description": "Calendrier salons geek/otaku/manga France — bloqué (403)",
            "status": "blocked",
            "events": 0,
        },
        {
            "name": "Rostercon",
            "key": "rostercon",
            "url": "https://www.rostercon.com/en/location/france-en",
            "description": "Conventions France — trop peu d'events (7), pas retenu",
            "status": "rejected",
            "events": 0,
        },
    ]

    return jsonify({
        "sources": sources,
        "total_events": len(convs),
        "cache_age_seconds": cache_age,
    })


@app.route("/api/test-alert", methods=["POST"])
def api_test_alert():
    # Hidden on purpose: unset or wrong password both return 404, so the
    # route doesn't reveal its own existence to anyone poking around.
    provided = request.headers.get("X-Settings-Password", "")
    if not settings_store.verify_password(provided):
        return jsonify({"error": "not found"}), 404

    from alerts import send_test_notification
    if send_test_notification():
        return jsonify({"ok": True})
    return jsonify({"error": "Webhook Discord absent ou envoi échoué"}), 500


@app.route("/settings")
def settings_page():
    return render_template("settings.html")


@app.route("/api/settings/status")
def api_settings_status():
    return jsonify({"configured": settings_store.is_configured()})


@app.route("/api/settings/setup", methods=["POST"])
def api_settings_setup():
    # First-time only: refuses once a password already exists, so a later
    # visitor can't silently take over an already-configured instance.
    if settings_store.is_configured():
        return jsonify({"error": "already configured"}), 409

    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if not password:
        return jsonify({"error": "password required"}), 400

    settings_store.set_up(
        discord_webhook_url=data.get("discord_webhook_url", ""),
        alert_city=data.get("alert_city", ""),
        alert_radius_km=float(data.get("alert_radius_km") or 50),
        password=password,
    )
    return jsonify({"ok": True})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    provided = request.headers.get("X-Settings-Password", "")
    if not settings_store.verify_password(provided):
        return jsonify({"error": "not found"}), 404

    if request.method == "GET":
        config = settings_store.load_config()
        return jsonify({
            "discord_webhook_url": config["discord_webhook_url"],
            "alert_city": config["alert_city"],
            "alert_radius_km": config["alert_radius_km"],
        })

    data = request.get_json(silent=True) or {}
    settings_store.update(
        discord_webhook_url=data.get("discord_webhook_url", ""),
        alert_city=data.get("alert_city", ""),
        alert_radius_km=float(data.get("alert_radius_km") or 50),
        new_password=data.get("new_password") or None,
    )
    return jsonify({"ok": True})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    global _last_manual_refresh

    # Global cooldown, not per-IP: the resource being protected (the 3rd-party
    # sites we scrape) is shared across all callers, so a single caller
    # hammering this route is just as damaging as many different ones. The
    # check-and-set happens under its own lock so two concurrent requests
    # can't both slip past the check before the timestamp is updated — the
    # scrape itself is serialized separately, inside get_conventions().
    with _cooldown_lock:
        elapsed = time.time() - _last_manual_refresh
        if elapsed < REFRESH_COOLDOWN_SECONDS:
            retry_after = int(REFRESH_COOLDOWN_SECONDS - elapsed)
            return jsonify({"error": "Trop de rafraîchissements, réessaie plus tard", "retry_after": retry_after}), 429, {"Retry-After": str(retry_after)}

        _last_manual_refresh = time.time()

    try:
        convs = get_conventions(force_refresh=True)
        return jsonify({"count": len(convs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _initial_load():
    logger.info("Initial load on startup...")
    try:
        convs = get_conventions()
        logger.info(f"Ready with {len(convs)} conventions")
    except Exception as e:
        logger.error(f"Startup load failed: {e}")


if __name__ == "__main__":
    # Run in the background so Flask starts accepting requests immediately,
    # even on a cold cache where the first scrape can take a while.
    threading.Thread(target=_initial_load, daemon=True).start()

    t = threading.Thread(target=_background_refresh, daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
