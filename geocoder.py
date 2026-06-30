import json
import os
import time
import re
import requests
import logging

logger = logging.getLogger(__name__)

CACHE_FILE = "cache/geocode_cache.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
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


def normalize_location(raw: str) -> str:
    """Extract city from location strings like 'Tours (37) - Parc des Expositions...'"""
    raw = raw.strip()

    # Strip venue/address after " - " separator: "City (37) - Venue name" → "City (37)"
    if " - " in raw:
        raw = raw.split(" - ")[0].strip()

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

    return f"{raw}, France"


def geocode(location: str) -> tuple[float, float] | None:
    """Return (lat, lon) for a location string, using cache."""
    if not _cache:
        _load_cache()

    normalized = normalize_location(location)
    if normalized in _cache:
        return tuple(_cache[normalized]) if _cache[normalized] else None

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
