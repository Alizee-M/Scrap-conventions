import json
import os
import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CACHE_FILE = "cache/conventions.json"
CACHE_TTL = 86400  # 24h
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


def _fetch(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except requests.RequestException as e:
        logger.error(f"Fetch error {url}: {e}")
        return None


# ─── Source 1 : lagendageek.com ───────────────────────────────────────────────

def _parse_lagendageek_event(el) -> dict | None:
    name_el = el.select_one("h4 a, h3 a, h2 a, .tribe-event-url a")
    if not name_el:
        return None
    name = name_el.get_text(strip=True)
    event_url = name_el.get("href", "")

    event_date = None
    time_el = el.select_one("time[datetime]")
    if time_el and time_el.get("datetime"):
        try:
            event_date = date.fromisoformat(time_el["datetime"][:10])
        except ValueError:
            pass
    if not event_date:
        for p in el.select("p"):
            parsed = _parse_date(p.get_text())
            if parsed:
                event_date = parsed
                break

    location = ""
    addr_el = el.select_one("address, .tribe-events-address")
    if addr_el:
        # Prefer just the venue-title line — addr_el.get_text(strip=True) would
        # otherwise mash it together with the street-address line with no space.
        venue_title = addr_el.select_one(".tribe-events-calendar-list__event-venue-title")
        location = venue_title.get_text(strip=True) if venue_title else addr_el.get_text(separator=" ", strip=True)
    else:
        for p in el.select("p"):
            text = p.get_text(strip=True)
            if text and not re.search(r"\d{4}|@|juil|juin|mai|avr|mars|jan|fev|août|sept|oct|nov|dec", text, re.I):
                location = text
                break
        if not location:
            ps = el.select("p")
            if ps:
                location = ps[-1].get_text(strip=True)

    img_el = el.select_one("img")
    image = img_el["src"] if img_el and img_el.get("src") else ""

    return {"name": name, "date": event_date.isoformat() if event_date else None,
            "location": location, "url": event_url, "image": image, "source": "lagendageek"}


def _select_lagendageek_events(soup: BeautifulSoup) -> list:
    events = soup.select(".event-item")
    if not events:
        events = soup.select(
            "article.tribe_events_cat, "
            "article[class*='type-tribe_events'], "
            ".tribe-events-loop .tribe-events-loop-event"
        )
    return events


def _parse_lagendageek_page(soup: BeautifulSoup, today: date) -> list[dict]:
    results = []
    for el in _select_lagendageek_events(soup):
        conv = _parse_lagendageek_event(el)
        if not conv:
            continue
        if conv["date"] and date.fromisoformat(conv["date"]) < today:
            continue
        results.append(conv)
    return results


def scrape_lagendageek(max_pages: int = 6) -> list[dict]:
    base = "https://lagendageek.com/liste-des-evenements/"
    today = date.today()
    results = []

    for page in range(1, max_pages + 1):
        url = base if page == 1 else f"{base}page/{page}/"
        soup = _fetch(url)
        if not soup:
            break

        if not _select_lagendageek_events(soup):
            logger.warning(f"lagendageek: no events on page {page}")
            break

        page_events = _parse_lagendageek_page(soup, today)
        results.extend(page_events)
        logger.info(f"lagendageek page {page}: {len(page_events)} events")
        time.sleep(1.2)

    return results


# ─── Source 2 : rom-game.fr ───────────────────────────────────────────────────

def _romgame_detail_location(event_url: str) -> str:
    """Fallback when the listing page has no location: read the city from the
    event's own page, in the .evt-hero-meta span next to the map-marker icon."""
    soup = _fetch(event_url)
    if not soup:
        return ""
    marker = soup.select_one(".evt-hero-meta i.fa-map-marker-alt")
    if not marker:
        return ""
    span = marker.find_parent("span")
    city_link = span.select_one("a") if span else None
    return city_link.get_text(strip=True) if city_link else ""


def _parse_romgame_page(soup: BeautifulSoup, today: date, fetch_detail_fallback: bool = True) -> list[dict]:
    results = []
    # Each event block: h3 with link, .event-category for location, p for date
    for h3 in soup.select("h3"):
        a = h3.select_one("a[href*='/agenda/']")
        if not a:
            continue
        name = a.get_text(strip=True)
        event_url = "https://www.rom-game.fr" + a["href"] if a["href"].startswith("/") else a["href"]

        # Location: "Category · City" line — old markup used .event-category,
        # current markup uses .event-meta-mobile / .event-meta-desktop.
        location = ""
        parent = h3.parent
        cat = parent.select_one(".event-category, .event-meta-mobile, .event-meta-desktop") if parent else None
        if cat:
            text = cat.get_text(separator=" ", strip=True)
            # Format: "Category · City" — keep city part
            parts = re.split(r"·|•", text)
            location = parts[-1].strip() if parts else text

        if not location and fetch_detail_fallback:
            location = _romgame_detail_location(event_url)
            time.sleep(0.6)

        # Date: next <p> after h3 containing a year or month name
        event_date = None
        for sibling in h3.find_next_siblings():
            t = sibling.get_text(strip=True)
            parsed = _parse_date(t)
            if parsed:
                event_date = parsed
                break
            if sibling.name == "h3":
                break

        if event_date and event_date < today:
            continue

        # Image: lives in the sibling .tag-horizontal-img-wrap, not under h3's
        # own parent (.tag-horizontal-body) — look one level up at .tag-horizontal.
        card = h3.parent.parent if h3.parent else None
        img_el = card.select_one("img") if card else None
        image = img_el["src"] if img_el and img_el.get("src") else ""

        results.append({
            "name": name,
            "date": event_date.isoformat() if event_date else None,
            "location": location,
            "url": event_url,
            "image": image,
            "source": "romgame",
        })

    return results


def scrape_romgame() -> list[dict]:
    url = "https://www.rom-game.fr/agenda/"
    today = date.today()
    soup = _fetch(url)
    if not soup:
        return []

    results = _parse_romgame_page(soup, today)
    logger.info(f"romgame: {len(results)} events")
    time.sleep(1.2)
    return results


# ─── Source 3 : bede.fr ───────────────────────────────────────────────────────

def _parse_bede_page(soup: BeautifulSoup, today: date) -> list[dict]:
    results = []
    # Each event is schema.org/Event microdata (the old [id^='festival'] markup is gone)
    for section in soup.select('[itemscope][itemtype="https://schema.org/Event"]'):
        name_el = section.select_one('h2[itemprop="name"]')
        if not name_el:
            continue
        name = name_el.get_text(strip=True)

        event_date = None
        start_el = section.select_one('meta[itemprop="startDate"]')
        if start_el and start_el.get("content"):
            try:
                event_date = date.fromisoformat(start_el["content"][:10])
            except ValueError:
                pass

        if event_date and event_date < today:
            continue

        # City + ISO country code from the structured address, e.g. "Bruxelles (BE)"
        # so normalize_location() can recognize it without guessing France by default.
        locality_el = section.select_one('[itemprop="address"] meta[itemprop="addressLocality"]')
        country_el = section.select_one('[itemprop="address"] meta[itemprop="addressCountry"]')
        city = locality_el["content"].strip() if locality_el and locality_el.get("content") else ""
        country = country_el["content"].strip() if country_el and country_el.get("content") else ""
        location = f"{city} ({country})" if city and country and country != "FR" else city

        url_el = section.select_one('a[itemprop="url"]')
        event_url = url_el["href"] if url_el and url_el.get("href") else ""

        img_el = section.select_one('img[itemprop="image"]')
        image = img_el["src"] if img_el and img_el.get("src") else ""

        results.append({
            "name": name,
            "date": event_date.isoformat() if event_date else None,
            "location": location,
            "url": event_url,
            "image": image,
            "source": "bede",
        })

    return results


def scrape_bede() -> list[dict]:
    url = "https://www.bede.fr/festivals-manga"
    today = date.today()
    soup = _fetch(url)
    if not soup:
        return []

    results = _parse_bede_page(soup, today)
    logger.info(f"bede: {len(results)} events")
    return results


# ─── Merge & dedup ────────────────────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.lower().strip())


def _deduplicate(events: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    unique = []
    for e in events:
        key = (_normalize_name(e["name"]), e["date"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def scrape_all() -> list[dict]:
    all_events: list[dict] = []
    health = {}

    sources = [
        (scrape_lagendageek, "lagendageek"),
        (scrape_romgame, "romgame"),
        (scrape_bede, "bede"),
    ]
    scraped_at = datetime.now().isoformat(timespec="seconds")

    # Each source is an independent, polite (self-throttled) HTTP scrape — run
    # them concurrently instead of waiting on one before starting the next.
    # Results are still merged in the fixed source order above so dedup
    # priority (first-seen wins) doesn't depend on which finishes first.
    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        futures = {label: executor.submit(scraper) for scraper, label in sources}
        for _, label in sources:
            try:
                events = futures[label].result()
                all_events.extend(events)
                logger.info(f"{label}: {len(events)} events scraped")
                health[label] = {"count": len(events), "scraped_at": scraped_at, "error": None}
                if len(events) == 0:
                    logger.error(f"{label}: scraper returned 0 events — the site likely changed structure")
            except Exception as e:
                logger.error(f"{label} scraper failed: {e}")
                health[label] = {"count": 0, "scraped_at": scraped_at, "error": str(e)}

    save_source_health(health)

    unique = _deduplicate(all_events)
    return sorted(unique, key=lambda x: x["date"] or "9999")


# ─── Cache ────────────────────────────────────────────────────────────────────

HEALTH_FILE = "cache/source_health.json"


def save_source_health(health: dict):
    """Raw per-source scrape counts (pre-dedup), so a source silently breaking
    isn't masked by another source happening to cover the same events."""
    os.makedirs("cache", exist_ok=True)
    with open(HEALTH_FILE, "w", encoding="utf-8") as f:
        json.dump(health, f, ensure_ascii=False, indent=2)


def load_source_health() -> dict:
    if not os.path.exists(HEALTH_FILE):
        return {}
    with open(HEALTH_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_cache() -> list[dict] | None:
    """Load whatever is cached on disk, regardless of age — staleness is handled by
    the daily background refresh, never by blocking a request with a synchronous re-scrape."""
    if not os.path.exists(CACHE_FILE):
        return None
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data or None


def save_cache(data: list[dict]):
    os.makedirs("cache", exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_conventions(force_refresh: bool = False) -> list[dict]:
    if not force_refresh:
        cached = load_cache()
        if cached is not None:
            return cached

    logger.info("Scraping all sources...")
    data = scrape_all()

    # Geocode at scrape time so coords are in cache — never at request time
    from geocoder import geocode
    logger.info(f"Geocoding {len(data)} events (this may take a while)...")
    for conv in data:
        if conv.get("location") and "lat" not in conv:
            coords = geocode(conv["location"])
            conv["lat"], conv["lon"] = (coords[0], coords[1]) if coords else (None, None)

    save_cache(data)
    logger.info(f"Total: {len(data)} events cached with coordinates")
    return data
