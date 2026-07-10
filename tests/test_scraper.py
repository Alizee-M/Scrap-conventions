"""Regression tests against real, saved HTML snapshots.

These exist because both rom-game.fr and bede.fr silently changed their HTML
structure in the past, and the app kept running while quietly losing data
(empty locations/images, or a source dropping to 0 events). If a site changes
its markup again, these tests should fail instead of the breakage going
unnoticed in production.

To refresh a fixture after a real, intentional site redesign:
    curl -s -A "Mozilla/5.0" <source url> -o tests/fixtures/<name>.html
then re-check the assertions below still describe events actually on the page.
"""
import time
from datetime import date

import pytest
import requests as requests_module
from bs4 import BeautifulSoup

import scraper


@pytest.fixture
def frozen_today(monkeypatch):
    """Pins scraper.date.today() to a fixed date, so the 'skip past events'
    filtering inside scrape_*() wrapper functions doesn't depend on whatever
    real calendar date the test suite happens to run on."""
    fixed = date(2020, 1, 1)

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed

    monkeypatch.setattr(scraper, "date", _FixedDate)
    return fixed


# ─── _fetch retry ───────────────────────────────────────────────────────────

def test_fetch_retries_transient_error_then_succeeds(monkeypatch):
    """A connection error on the first attempt shouldn't be fatal — it's
    what used to make a single dropped packet look identical to a source
    being genuinely broken (see check_source_health)."""
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    class FakeResponse:
        status_code = 200
        text = "<html></html>"

        def raise_for_status(self):
            pass

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise requests_module.exceptions.ConnectionError("boom")
        return FakeResponse()

    monkeypatch.setattr(scraper.requests, "get", fake_get)

    assert scraper._fetch("https://example.com") is not None
    assert calls["n"] == 2


def test_fetch_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        raise requests_module.exceptions.Timeout("timeout")

    monkeypatch.setattr(scraper.requests, "get", fake_get)

    assert scraper._fetch("https://example.com") is None
    assert calls["n"] == scraper.FETCH_RETRIES


def test_fetch_does_not_retry_on_404(monkeypatch):
    calls = {"n": 0}

    class FakeResponse:
        status_code = 404

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return FakeResponse()

    monkeypatch.setattr(scraper.requests, "get", fake_get)

    assert scraper._fetch("https://example.com") is None
    assert calls["n"] == 1


# ─── scrape_all ─────────────────────────────────────────────────────────────

def test_scrape_all_dedup_priority_is_source_order_not_completion_order(monkeypatch):
    """The 3 scrapers run concurrently now, but when two sources cover the
    same (name, date) event, the one earlier in the fixed source list
    [lagendageek, romgame, bede] must still win — regardless of which
    thread happens to finish first."""
    same_event_lagendageek = {
        "name": "Dup Con", "date": "2026-09-01", "location": "From lagendageek",
        "url": "https://lagendageek.com/x", "image": "", "source": "lagendageek",
    }
    same_event_romgame = {
        "name": "Dup Con", "date": "2026-09-01", "location": "From romgame",
        "url": "https://romgame.fr/x", "image": "", "source": "romgame",
    }

    def slow_lagendageek():
        time.sleep(0.05)  # finishes second
        return [same_event_lagendageek]

    def fast_romgame():
        return [same_event_romgame]  # finishes first, but must still lose

    monkeypatch.setattr(scraper, "scrape_lagendageek", slow_lagendageek)
    monkeypatch.setattr(scraper, "scrape_romgame", fast_romgame)
    monkeypatch.setattr(scraper, "scrape_bede", lambda: [])
    monkeypatch.setattr(scraper, "save_source_health", lambda health: None)

    result = scraper.scrape_all()
    assert len(result) == 1
    assert result[0]["location"] == "From lagendageek"


# ─── lagendageek.com ───────────────────────────────────────────────────────

def test_lagendageek_parses_known_event(load_fixture, fixed_today):
    soup = load_fixture("lagendageek.html")
    events = scraper._parse_lagendageek_page(soup, fixed_today)

    assert len(events) > 10

    by_name = {e["name"]: e for e in events}
    event = by_name["Japan Tours Festival 2026"]
    assert event["date"] == "2026-07-03"
    assert event["location"] == "Tours (37) – Parc des Expositions de Tours"
    assert event["url"] == "https://lagendageek.com/tevent/japan-tours-festival-2026/"
    assert event["image"]
    assert event["source"] == "lagendageek"


def test_lagendageek_all_events_have_name_and_url(load_fixture, fixed_today):
    soup = load_fixture("lagendageek.html")
    events = scraper._parse_lagendageek_page(soup, fixed_today)
    for e in events:
        assert e["name"]
        assert e["url"]


# ─── rom-game.fr ────────────────────────────────────────────────────────────

def test_romgame_parses_known_events(load_fixture, fixed_today):
    soup = load_fixture("romgame.html")
    events = scraper._parse_romgame_page(soup, fixed_today, fetch_detail_fallback=False)

    assert len(events) > 50

    by_name = {e["name"]: e for e in events}

    magic = by_name["Magic Odyssey 2026"]
    assert magic["date"] == "2026-07-03"
    assert magic["location"] == "Souterraine"
    assert magic["url"] == "https://www.rom-game.fr/agenda/8241-magic+odyssey.html"
    assert magic["image"] == (
        "https://www.rom-game.fr/multimedia/agendaM/magic-odyssey-souterraine-20260123-120907.webp"
    )

    comiccon = by_name["Comiccon de Montréal 2026"]
    assert comiccon["location"] == "Montréal"
    assert comiccon["image"]


def test_romgame_no_network_call_when_fallback_disabled(load_fixture, fixed_today):
    """fetch_detail_fallback=False must never hit the network, even for events
    whose listing-page location would otherwise be empty."""
    soup = load_fixture("romgame.html")
    events = scraper._parse_romgame_page(soup, fixed_today, fetch_detail_fallback=False)
    assert all(isinstance(e["location"], str) for e in events)


def test_romgame_detail_location_fallback(load_fixture, monkeypatch):
    """When the listing page has no location, scraper falls back to the
    event's own page and reads .evt-hero-meta's map-marker span."""
    detail_soup = load_fixture("romgame_detail_magic_odyssey.html")
    monkeypatch.setattr(scraper, "_fetch", lambda url: detail_soup)
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)

    location = scraper._romgame_detail_location("https://www.rom-game.fr/agenda/8241-magic+odyssey.html")
    assert location == "Souterraine"


# ─── bede.fr ──────────────────────────────────────────────────────────────

def test_bede_parses_known_events(load_fixture, fixed_today):
    soup = load_fixture("bede.html")
    events = scraper._parse_bede_page(soup, fixed_today)

    assert len(events) == 2
    by_name = {e["name"]: e for e in events}

    e1 = by_name["2ème édition du festival Japan Bibli Gaming"]
    assert e1["date"] == "2026-08-01"
    assert e1["location"] == "Saint-Germain-du-Puy"
    assert e1["url"] == "https://www.bede.fr/festivals-manga#festival2911"

    e2 = by_name["6ème édition du Hashtag festival de Bourg-en-Bresse"]
    assert e2["date"] == "2026-10-17"
    assert e2["location"] == "Bourg-en-Bresse"


def test_bede_french_events_have_no_country_suffix(load_fixture, fixed_today):
    """addressCountry feeds straight into normalize_location()'s existing
    'City (XX)' pattern so foreign events don't default to France — but for
    France itself, the location stays a bare city name."""
    soup = load_fixture("bede.html")
    for section in soup.select('[itemscope][itemtype="https://schema.org/Event"]'):
        country_el = section.select_one('[itemprop="address"] meta[itemprop="addressCountry"]')
        assert country_el is not None and country_el["content"] == "FR"

    events = scraper._parse_bede_page(soup, fixed_today)
    for e in events:
        assert "(" not in e["location"]


def test_parse_bede_page_skips_section_without_name(fixed_today):
    soup = BeautifulSoup(
        '<div itemscope itemtype="https://schema.org/Event">'
        '<meta itemprop="startDate" content="2026-07-03"></div>',
        "lxml",
    )
    assert scraper._parse_bede_page(soup, fixed_today) == []


def test_parse_bede_page_handles_malformed_start_date(fixed_today):
    soup = BeautifulSoup(
        '<div itemscope itemtype="https://schema.org/Event">'
        '<h2 itemprop="name">Test Con</h2>'
        '<meta itemprop="startDate" content="not-a-date"></div>',
        "lxml",
    )
    events = scraper._parse_bede_page(soup, fixed_today)
    assert events[0]["date"] is None


def test_parse_bede_page_skips_past_events():
    soup = BeautifulSoup(
        '<div itemscope itemtype="https://schema.org/Event">'
        '<h2 itemprop="name">Old Con</h2>'
        '<meta itemprop="startDate" content="2019-01-01"></div>',
        "lxml",
    )
    assert scraper._parse_bede_page(soup, date(2020, 1, 1)) == []


def test_scrape_bede_returns_empty_when_fetch_fails(monkeypatch):
    monkeypatch.setattr(scraper, "_fetch", lambda url: None)
    assert scraper.scrape_bede() == []


def test_scrape_bede_happy_path(monkeypatch, load_fixture, frozen_today):
    soup = load_fixture("bede.html")
    monkeypatch.setattr(scraper, "_fetch", lambda url: soup)

    results = scraper.scrape_bede()

    assert len(results) == 2


# ─── _parse_date ────────────────────────────────────────────────────────────

def test_parse_date_empty_text_returns_none():
    assert scraper._parse_date("") is None
    assert scraper._parse_date(None) is None


def test_parse_date_no_month_returns_none():
    assert scraper._parse_date("quelque part en 2026") is None


def test_parse_date_no_day_returns_none():
    assert scraper._parse_date("juillet 2026") is None


def test_parse_date_invalid_day_for_month_returns_none():
    """31 février n'existe pas : date() lève ValueError, doit être absorbée."""
    assert scraper._parse_date("31 fevrier 2026") is None


def test_parse_date_defaults_to_current_year_when_absent():
    from datetime import datetime
    assert scraper._parse_date("3 juillet") == date(datetime.now().year, 7, 3)


# ─── _parse_lagendageek_event ───────────────────────────────────────────────

def test_parse_lagendageek_event_returns_none_without_name():
    soup = BeautifulSoup('<div class="event-item"><p>Tours</p></div>', "lxml")
    el = soup.select_one(".event-item")
    assert scraper._parse_lagendageek_event(el) is None


def test_parse_lagendageek_event_falls_back_to_paragraph_date_on_bad_datetime_attr():
    soup = BeautifulSoup(
        '<div class="event-item">'
        '<h4><a href="https://example.com/x">Test Con</a></h4>'
        '<time datetime="not-a-date"></time>'
        "<p>3 juillet 2026</p></div>",
        "lxml",
    )
    conv = scraper._parse_lagendageek_event(soup.select_one(".event-item"))
    assert conv["date"] == "2026-07-03"


def test_parse_lagendageek_event_location_from_first_non_date_paragraph():
    soup = BeautifulSoup(
        '<div class="event-item">'
        '<h4><a href="https://example.com/x">Test Con</a></h4>'
        "<p>Tours</p><p>3 juillet 2026</p></div>",
        "lxml",
    )
    conv = scraper._parse_lagendageek_event(soup.select_one(".event-item"))
    assert conv["location"] == "Tours"


def test_parse_lagendageek_event_location_falls_back_to_last_paragraph_when_all_look_like_dates():
    soup = BeautifulSoup(
        '<div class="event-item">'
        '<h4><a href="https://example.com/x">Test Con</a></h4>'
        "<p>3 juillet 2026</p></div>",
        "lxml",
    )
    conv = scraper._parse_lagendageek_event(soup.select_one(".event-item"))
    assert conv["location"] == "3 juillet 2026"


# ─── scrape_lagendageek pagination ──────────────────────────────────────────

def _lagendageek_event_html(name, url, date_text):
    return (
        '<div class="event-item">'
        f'<h4><a href="{url}">{name}</a></h4>'
        f"<p>{date_text}</p></div>"
    )


def test_parse_lagendageek_page_skips_unparseable_and_past_events(fixed_today):
    html = (
        '<div class="event-item"><p>no name here, unparseable</p></div>'
        '<div class="event-item"><h4><a href="https://example.com/old">Old Con</a></h4>'
        '<p>3 janvier 2019</p></div>'
        '<div class="event-item"><h4><a href="https://example.com/new">New Con</a></h4>'
        '<p>3 juillet 2026</p></div>'
    )
    soup = BeautifulSoup(html, "lxml")

    events = scraper._parse_lagendageek_page(soup, fixed_today)

    assert [e["name"] for e in events] == ["New Con"]


def test_scrape_lagendageek_stops_when_first_fetch_fails(monkeypatch):
    monkeypatch.setattr(scraper, "_fetch", lambda url: None)
    assert scraper.scrape_lagendageek() == []


def test_scrape_lagendageek_stops_when_page_has_no_events(monkeypatch):
    empty_soup = BeautifulSoup("<html><body>rien ici</body></html>", "lxml")
    monkeypatch.setattr(scraper, "_fetch", lambda url: empty_soup)
    assert scraper.scrape_lagendageek() == []


def test_scrape_lagendageek_paginates_until_a_page_fails(monkeypatch, frozen_today):
    page1 = BeautifulSoup(_lagendageek_event_html("Con A", "https://example.com/a", "3 juillet 2026"), "lxml")
    page2 = BeautifulSoup(_lagendageek_event_html("Con B", "https://example.com/b", "4 juillet 2026"), "lxml")
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        return {1: page1, 2: page2}.get(len(fetched))

    monkeypatch.setattr(scraper, "_fetch", fake_fetch)
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)

    results = scraper.scrape_lagendageek(max_pages=3)

    assert len(fetched) == 3  # page 1 & 2 succeed, page 3 returns None -> loop stops
    assert {e["name"] for e in results} == {"Con A", "Con B"}


# ─── rom-game.fr detail fallback & edge cases ───────────────────────────────

def test_romgame_detail_location_no_soup(monkeypatch):
    monkeypatch.setattr(scraper, "_fetch", lambda url: None)
    assert scraper._romgame_detail_location("https://example.com/x") == ""


def test_romgame_detail_location_no_marker(monkeypatch):
    soup = BeautifulSoup('<div class="evt-hero-meta">pas de marqueur ici</div>', "lxml")
    monkeypatch.setattr(scraper, "_fetch", lambda url: soup)
    assert scraper._romgame_detail_location("https://example.com/x") == ""


def test_scrape_romgame_returns_empty_when_fetch_fails(monkeypatch):
    monkeypatch.setattr(scraper, "_fetch", lambda url: None)
    assert scraper.scrape_romgame() == []


def test_scrape_romgame_happy_path(monkeypatch, load_fixture, frozen_today):
    soup = load_fixture("romgame.html")
    monkeypatch.setattr(scraper, "_fetch", lambda url: soup)
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)

    results = scraper.scrape_romgame()

    assert len(results) > 50


def test_romgame_page_uses_detail_fallback_when_listing_has_no_location(monkeypatch, fixed_today):
    soup = BeautifulSoup(
        '<div class="tag-horizontal"><div class="tag-horizontal-body">'
        '<h3><a href="/agenda/1-test.html">Test Con</a></h3>'
        "</div></div>",
        "lxml",
    )
    detail_soup = BeautifulSoup(
        '<span class="evt-hero-meta"><i class="fa-map-marker-alt"></i><a>Nantes</a></span>', "lxml"
    )
    monkeypatch.setattr(scraper, "_fetch", lambda url: detail_soup)
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)

    events = scraper._parse_romgame_page(soup, fixed_today, fetch_detail_fallback=True)

    assert events[0]["location"] == "Nantes"


def test_romgame_page_date_search_stops_at_next_event_h3(fixed_today):
    """The date lookup after an h3 must not spill into the next event's own
    paragraphs when this event has none of its own."""
    soup = BeautifulSoup(
        '<div class="tag-horizontal-body">'
        '<h3><a href="/agenda/1-test.html">Con A</a></h3>'
        '<h3><a href="/agenda/2-test.html">Con B</a></h3>'
        "<p>3 juillet 2026</p></div>",
        "lxml",
    )
    events = scraper._parse_romgame_page(soup, fixed_today, fetch_detail_fallback=False)
    by_name = {e["name"]: e for e in events}
    assert by_name["Con A"]["date"] is None
    assert by_name["Con B"]["date"] == "2026-07-03"


def test_romgame_page_skips_past_events():
    soup = BeautifulSoup(
        '<div class="tag-horizontal-body">'
        '<h3><a href="/agenda/1-test.html">Old Con</a></h3>'
        '<p class="event-category">Category · Paris</p>'
        "<p>3 janvier 2019</p></div>",
        "lxml",
    )
    events = scraper._parse_romgame_page(soup, date(2020, 1, 1), fetch_detail_fallback=False)
    assert events == []


# ─── scrape_all error handling ──────────────────────────────────────────────

def test_scrape_all_records_error_when_a_scraper_raises(monkeypatch):
    def _raise():
        raise RuntimeError("boom")

    monkeypatch.setattr(scraper, "scrape_lagendageek", _raise)
    monkeypatch.setattr(scraper, "scrape_romgame", lambda: [])
    monkeypatch.setattr(scraper, "scrape_bede", lambda: [])

    saved_health = {}
    monkeypatch.setattr(scraper, "save_source_health", lambda health: saved_health.update(health))
    monkeypatch.setattr("alerts.check_source_health", lambda health: None)

    result = scraper.scrape_all()

    assert result == []
    assert saved_health["lagendageek"]["error"] == "boom"
    assert saved_health["lagendageek"]["count"] == 0
    assert saved_health["romgame"]["error"] is None


# ─── cache & source-health persistence ──────────────────────────────────────

def test_save_and_load_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "CACHE_FILE", str(tmp_path / "conventions.json"))

    scraper.save_cache([{"name": "Con"}])

    assert scraper.load_cache() == [{"name": "Con"}]


def test_load_cache_returns_none_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "CACHE_FILE", str(tmp_path / "missing.json"))
    assert scraper.load_cache() is None


def test_load_cache_returns_none_for_empty_list(tmp_path, monkeypatch):
    cache_file = tmp_path / "conventions.json"
    monkeypatch.setattr(scraper, "CACHE_FILE", str(cache_file))
    scraper.save_cache([])
    assert scraper.load_cache() is None


def test_save_and_load_source_health_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "HEALTH_FILE", str(tmp_path / "source_health.json"))

    scraper.save_source_health({"bede": {"count": 2, "scraped_at": "x", "error": None}})

    assert scraper.load_source_health() == {"bede": {"count": 2, "scraped_at": "x", "error": None}}


def test_load_source_health_returns_empty_dict_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "HEALTH_FILE", str(tmp_path / "missing.json"))
    assert scraper.load_source_health() == {}


# ─── get_conventions ─────────────────────────────────────────────────────────

def test_get_conventions_rechecks_cache_after_acquiring_lock(tmp_path, monkeypatch):
    """Two cold-start requests can race to the lock; the loser must return the
    winner's freshly-scraped cache instead of scraping a second time."""
    cache_file = tmp_path / "conventions.json"
    monkeypatch.setattr(scraper, "CACHE_FILE", str(cache_file))

    load_cache_calls = []
    real_load_cache = scraper.load_cache

    def fake_load_cache():
        load_cache_calls.append(1)
        if len(load_cache_calls) == 1:
            return None  # first check (before the lock): cache still cold
        return real_load_cache()  # second check (inside the lock): a racing thread just filled it

    scraper.save_cache([{"name": "Filled By Racing Thread"}])
    monkeypatch.setattr(scraper, "load_cache", fake_load_cache)

    def fail_scrape_all():
        raise AssertionError("scrape_all should not run once the recheck inside the lock finds a warm cache")

    monkeypatch.setattr(scraper, "scrape_all", fail_scrape_all)

    result = scraper.get_conventions()

    assert result == [{"name": "Filled By Racing Thread"}]
    assert len(load_cache_calls) == 2


def test_get_conventions_returns_cached_data_without_scraping(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "CACHE_FILE", str(tmp_path / "conventions.json"))
    scraper.save_cache([{"name": "Cached Con"}])

    def fail_scrape_all():
        raise AssertionError("scrape_all should not run when the cache is warm")

    monkeypatch.setattr(scraper, "scrape_all", fail_scrape_all)

    assert scraper.get_conventions() == [{"name": "Cached Con"}]


def test_get_conventions_force_refresh_scrapes_geocodes_and_saves(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "CACHE_FILE", str(tmp_path / "conventions.json"))
    scraper.save_cache([{"name": "Stale Con"}])

    fresh = [{"name": "Fresh Con", "location": "Tours"}]
    monkeypatch.setattr(scraper, "scrape_all", lambda: fresh)

    geocode_calls = []
    monkeypatch.setattr("geocoder.geocode", lambda loc: geocode_calls.append(loc) or (47.39, 0.68))

    notify_calls = []
    monkeypatch.setattr("alerts.check_and_notify", lambda data: notify_calls.append(data))

    result = scraper.get_conventions(force_refresh=True)

    assert result[0]["name"] == "Fresh Con"
    assert result[0]["lat"] == 47.39 and result[0]["lon"] == 0.68
    assert geocode_calls == ["Tours"]
    assert notify_calls == [result]
    assert scraper.load_cache()[0]["name"] == "Fresh Con"


def test_get_conventions_skips_geocoding_when_location_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "CACHE_FILE", str(tmp_path / "conventions.json"))
    monkeypatch.setattr(scraper, "scrape_all", lambda: [{"name": "No Location Con", "location": ""}])

    def fail_geocode(loc):
        raise AssertionError("geocode should not be called for an event without a location")

    monkeypatch.setattr("geocoder.geocode", fail_geocode)
    monkeypatch.setattr("alerts.check_and_notify", lambda data: None)

    result = scraper.get_conventions(force_refresh=True)

    assert "lat" not in result[0]
