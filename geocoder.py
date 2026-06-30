import json
import os
import time
import re
import requests
import logging

logger = logging.getLogger(__name__)

CACHE_FILE = "cache/geocode_cache.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
BAN_URL = "https://api-adresse.data.gouv.fr/search/"
BAN_MIN_SCORE = 0.5
HEADERS = {"User-Agent": "ScrapConventions/1.0 (alizeemeyer@gmail.com)"}

_cache = {}
_last_request = 0.0


def _load_cache():
    global _cache
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            _cache = json.load(f)


def _save_cache():
    os.makedirs("cache", exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False, indent=2)


def _nominatim_query(q: str) -> tuple[float, float] | None:
    global _last_request
    elapsed = time.time() - _last_request
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)

    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": q, "format": "json", "limit": 1},
            headers=HEADERS,
            timeout=10,
        )
        _last_request = time.time()
        data = resp.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        logger.warning(f"Nominatim error for '{q}': {e}")
    return None


def _ban_query(city: str) -> tuple[float, float] | None:
    """French government address API (api-adresse.data.gouv.fr) — fast, no rate limit, France only."""
    try:
        resp = requests.get(
            BAN_URL,
            params={"q": city, "type": "municipality", "limit": 1},
            timeout=5,
        )
        resp.raise_for_status()
        features = resp.json().get("features", [])
        if features and features[0]["properties"]["score"] >= BAN_MIN_SCORE:
            lon, lat = features[0]["geometry"]["coordinates"]
            return lat, lon
    except (requests.RequestException, KeyError, ValueError) as e:
        logger.warning(f"BAN error for '{city}': {e}")
    return None


def normalize_location(raw: str) -> str:
    """Extract city from location strings like 'Tours (37) - Parc des Expositions...'"""
    raw = raw.strip()

    # Strip venue/address after a " - "/" – "/" — " separator: "City (37) – Venue name" → "City (37)"
    raw = re.split(r"\s[-–—]\s", raw, maxsplit=1)[0].strip()

    # "City (dept_number)" → French city
    m = re.match(r"^(.+?)\s*\(\d+\)\s*$", raw)
    if m:
        return f"{m.group(1).strip()}, France"

    # "City (BE/CH/ES/LU/DE)" → neighboring country
    country_codes = {"BE": "Belgium", "CH": "Switzerland", "ES": "Spain", "LU": "Luxembourg", "DE": "Germany", "NL": "Netherlands"}
    m = re.match(r"^(.+?)\s*\(([A-Z]{2})\)\s*$", raw)
    if m and m.group(2) in country_codes:
        return f"{m.group(1).strip()}, {country_codes[m.group(2)]}"

    # French/Dutch country names in text
    country_map = {
        "belgique": "Belgium", "belgië": "Belgium",
        "suisse": "Switzerland", "schweiz": "Switzerland",
        "espagne": "Spain",
        "luxembourg": "Luxembourg",
        "allemagne": "Germany",
    }
    lower = raw.lower()
    for fr, en in country_map.items():
        if fr in lower:
            city = re.sub(r",?\s*" + fr, "", raw, flags=re.IGNORECASE).strip()
            return f"{city}, {en}"

    if re.search(r"\b(belgium|spain|switzerland|netherlands)\b", lower):
        return raw

    # No explicit country signal in the text — default to France, since the
    # vast majority of sources we scrape are French listings with bare city
    # names ("Tours", "Souterraine"...). Known limitation: a bare name that
    # happens to collide with an obscure French homonym of a famous foreign
    # city (e.g. rom-game.fr's "Montréal" — there's also a 2 000-person
    # village called Montréal in Aude) will resolve to the French village
    # instead. Fixing this generally would mean skipping the fast/accurate
    # BAN lookup for every unmarked French city just to catch rare name
    # collisions, which isn't worth the cost — accepted as-is.
    return f"{raw}, France"


def geocode(location: str) -> tuple[float, float] | None:
    """Return (lat, lon) for a location string, using cache."""
    if not _cache:
        _load_cache()

    normalized = normalize_location(location)
    if normalized in _cache:
        return tuple(_cache[normalized]) if _cache[normalized] else None

    result = None
    if normalized.endswith(", France"):
        result = _ban_query(normalized[: -len(", France")])
    if not result:
        result = _nominatim_query(normalized)

    _cache[normalized] = list(result) if result else None
    _save_cache()
    return result


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in km between two lat/lon points."""
    from math import radians, sin, cos, sqrt, atan2

    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))
