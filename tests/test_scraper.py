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

import requests as requests_module
import scraper


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
