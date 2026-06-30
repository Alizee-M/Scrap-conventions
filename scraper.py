import json
import os
import re
import time
import logging
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CACHE_FILE = "cache/conventions.json"
CACHE_TTL = 86400  # 24h
BASE_URL = "https://lagendageek.com/liste-des-evenements/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}

FRENCH_MONTHS = {
    "janv": 1, "jan": 1, "janvier": 1,
    "fevr": 2, "fev": 2, "février": 2, "fevrier": 2,
    "mars": 3,
    "avr": 4, "avril": 4,
    "mai": 5,
    "juin": 6,
    "juil": 7, "juillet": 7,
    "aout": 8, "août": 8,
    "sept": 9, "septembre": 9,
    "oct": 10, "octobre": 10,
    "nov": 11, "novembre": 11,
    "dec": 12, "déc": 12, "decembre": 12, "décembre": 12,
}


def _parse_date(text: str) -> date | None:
    if not text:
        return None
    s = text.strip().lower()
    # Normalize accents for month matching
    s = s.replace("é", "e").replace("è", "e").replace("û", "u").replace(".", "")

    year_m = re.search(r"(20\d\d)", s)
    year = int(year_m.group(1)) if year_m else datetime.now().year

    month = None
    for key, val in FRENCH_MONTHS.items():
        if re.search(r"\b" + key + r"\b", s):
            month = val
            break
    if not month:
        return None

    days = [int(d) for d in re.findall(r"\b(\d{1,2})\b", s) if int(d) <= 31]
    if not days:
        return None

    try:
        return date(year, month, days[0])
    except ValueError:
        return None


def _fetch_page(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except requests.RequestException as e:
        logger.error(f"Fetch error {url}: {e}")
        return None


def _parse_event(el) -> dict | None:
    # Name
    name_el = el.select_one("h4 a, h3 a, h2 a, .tribe-event-url a")
    if not name_el:
        return None
    name = name_el.get_text(strip=True)
    event_url = name_el.get("href", "")

    # Date — try datetime attribute first
    event_date = None
    time_el = el.select_one("time[datetime]")
    if time_el and time_el.get("datetime"):
        try:
            event_date = date.fromisoformat(time_el["datetime"][:10])
        except ValueError:
            pass

    # Fallback: parse paragraph text
    if not event_date:
        for p in el.select("p"):
            parsed = _parse_date(p.get_text())
            if parsed:
                event_date = parsed
                break

    # Location — 3rd <p> or address element
    location = ""
    addr_el = el.select_one("address, .tribe-events-address")
    if addr_el:
        location = addr_el.get_text(strip=True)
    else:
        ps = el.select("p")
        for p in ps:
            text = p.get_text(strip=True)
            # Skip date-like paragraphs
            if text and not re.search(r"\d{4}|@|juil|juin|mai|avr|mars|jan|fev|août|sept|oct|nov|dec", text, re.I):
                location = text
                break
        if not location and len(ps) >= 2:
            location = ps[-1].get_text(strip=True)

    # Image
    img_el = el.select_one("img")
    image = img_el["src"] if img_el and img_el.get("src") else ""

    return {
        "name": name,
        "date": event_date.isoformat() if event_date else None,
        "location": location,
        "url": event_url,
        "image": image,
    }


def scrape(max_pages: int = 6) -> list[dict]:
    today = date.today()
    results = []

    for page in range(1, max_pages + 1):
        url = BASE_URL if page == 1 else f"{BASE_URL}page/{page}/"
        soup = _fetch_page(url)
        if not soup:
            break

        events = soup.select(".event-item")
        if not events:
            # Fallback selectors for The Events Calendar
            events = soup.select(
                "article.tribe_events_cat, "
                "article[class*='type-tribe_events'], "
                ".tribe-events-loop .tribe-events-loop-event"
            )

        if not events:
            logger.warning(f"No events found on page {page}, stopping")
            break

        found = 0
        for el in events:
            conv = _parse_event(el)
            if not conv:
                continue
            # Only keep future events
            if conv["date"]:
                try:
                    if date.fromisoformat(conv["date"]) < today:
                        continue
                except ValueError:
                    pass
            results.append(conv)
            found += 1

        logger.info(f"Page {page}: {found} events")
        time.sleep(1.2)

    # Deduplicate by name + date
    seen = set()
    unique = []
    for c in results:
        key = (c["name"].lower(), c["date"])
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return sorted(unique, key=lambda x: x["date"] or "9999")


def load_cache() -> list[dict] | None:
    if not os.path.exists(CACHE_FILE):
        return None
    stat = os.stat(CACHE_FILE)
    if time.time() - stat.st_mtime > CACHE_TTL:
        return None
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cache(data: list[dict]):
    os.makedirs("cache", exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_conventions(force_refresh: bool = False) -> list[dict]:
    if not force_refresh:
        cached = load_cache()
        if cached is not None:
            return cached

    logger.info("Scraping lagendageek.com...")
    data = scrape()
    save_cache(data)
    logger.info(f"Scraped {len(data)} upcoming events")
    return data
