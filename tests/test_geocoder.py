import time

import requests

import geocoder


def test_normalize_location_dept_number():
    assert geocoder.normalize_location("Tours (37)") == "Tours, France"


def test_normalize_location_strips_venue_after_ascii_dash():
    assert geocoder.normalize_location("Tours (37) - Parc des Expositions") == "Tours, France"


def test_normalize_location_strips_venue_after_en_dash():
    """Regression: lagendageek.com uses an en-dash ('–') between city and venue,
    which the old ASCII-only ' - ' split silently failed to strip."""
    assert geocoder.normalize_location("Tours (37) – Parc des Expositions de Tours") == "Tours, France"


def test_normalize_location_country_code_suffix():
    assert geocoder.normalize_location("Bruxelles (BE)") == "Bruxelles, Belgium"
    assert geocoder.normalize_location("Herstal (BE) – Espace Marexhe") == "Herstal, Belgium"


def test_normalize_location_country_name_in_text():
    assert geocoder.normalize_location("Lausanne, Suisse") == "Lausanne, Switzerland"


def test_normalize_location_defaults_to_france():
    assert geocoder.normalize_location("Saint-Estève") == "Saint-Estève, France"


def test_normalize_location_recognized_english_country_name_left_untouched():
    """When the source text already names the country in English (no French/Dutch
    match, no dept-number or ISO-code suffix), normalize_location() must not
    tack on ', France' — the country signal is already there."""
    assert geocoder.normalize_location("Ghent, Belgium") == "Ghent, Belgium"


def test_ban_query_used_for_french_city(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"features": [{
                    "properties": {"score": 0.95, "city": "Saint-Estève"},
                    "geometry": {"coordinates": [2.85, 42.71]},
                }]}
        return Resp()

    monkeypatch.setattr(geocoder.requests, "get", fake_get)
    monkeypatch.setattr(geocoder, "_load_cache", lambda: None)
    monkeypatch.setattr(geocoder, "_save_cache", lambda: None)
    monkeypatch.setattr(geocoder, "_cache", {})

    result = geocoder.geocode("Saint-Estève")
    assert result == (42.71, 2.85)
    assert any("api-adresse.data.gouv.fr" in c for c in calls)


def test_ban_query_rejects_name_lookalike(monkeypatch):
    """Regression: querying "La Louvière" (a real Belgian city, scraped with no country
    marker) used to match BAN's "La Louvière-Lauragais" — an 80-person French hamlet with
    a similar name — because its score (0.83) cleared BAN_MIN_SCORE despite being the
    wrong place entirely. BAN must reject non-exact name matches so this falls through to
    Nominatim, which finds the actual (foreign) city instead."""
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(url)
        if "api-adresse" in url:
            class BanResp:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"features": [{
                        "properties": {"score": 0.83, "city": "La Louvière-Lauragais"},
                        "geometry": {"coordinates": [1.75, 43.27]},
                    }]}
            return BanResp()

        class NomResp:
            def raise_for_status(self):
                pass

            def json(self):
                return [{"lat": "50.48", "lon": "4.19"}]
        return NomResp()

    monkeypatch.setattr(geocoder.requests, "get", fake_get)
    monkeypatch.setattr(geocoder, "_load_cache", lambda: None)
    monkeypatch.setattr(geocoder, "_save_cache", lambda: None)
    monkeypatch.setattr(geocoder, "_cache", {})
    monkeypatch.setattr(geocoder, "_last_request", 0.0)

    result = geocoder.geocode("La Louvière")
    assert result == (50.48, 4.19)
    assert any("api-adresse" in c for c in calls)
    assert any("nominatim" in c for c in calls)


def test_geocode_skips_ban_for_non_french_city(monkeypatch):
    """BAN (api-adresse.data.gouv.fr) only covers France. geocode() must only
    try it when normalize_location() resolved the country to France — for a
    recognized foreign city it should go straight to Nominatim."""
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(url)
        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return [{"lat": "50.85", "lon": "4.35"}]
        return Resp()

    monkeypatch.setattr(geocoder.requests, "get", fake_get)
    monkeypatch.setattr(geocoder, "_load_cache", lambda: None)
    monkeypatch.setattr(geocoder, "_save_cache", lambda: None)
    monkeypatch.setattr(geocoder, "_cache", {})
    monkeypatch.setattr(geocoder, "_last_request", 0.0)

    result = geocoder.geocode("Bruxelles (BE)")
    assert result == (50.85, 4.35)
    assert len(calls) == 1
    assert "nominatim" in calls[0]


def test_geocode_returns_cached_result_without_any_network_call(monkeypatch):
    monkeypatch.setattr(geocoder, "_load_cache", lambda: None)
    monkeypatch.setattr(geocoder, "_cache", {"Tours, France": [47.39, 0.68]})

    def fail_get(*a, **k):
        raise AssertionError("a cache hit must not touch the network")

    monkeypatch.setattr(geocoder.requests, "get", fail_get)

    assert geocoder.geocode("Tours") == (47.39, 0.68)


def test_geocode_returns_none_for_a_cached_previous_miss(monkeypatch):
    """A location that failed to geocode last time is cached as None so it
    isn't retried (and doesn't hammer Nominatim) on every subsequent scrape."""
    monkeypatch.setattr(geocoder, "_load_cache", lambda: None)
    monkeypatch.setattr(geocoder, "_cache", {"Nulle Part, France": None})

    monkeypatch.setattr(geocoder.requests, "get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("a cache hit must not touch the network")
    ))

    assert geocoder.geocode("Nulle Part") is None


# ─── cache file I/O ─────────────────────────────────────────────────────────

def test_load_and_save_cache_roundtrip(tmp_path, monkeypatch):
    cache_file = tmp_path / "geocode_cache.json"
    monkeypatch.setattr(geocoder, "CACHE_FILE", str(cache_file))
    monkeypatch.setattr(geocoder, "_cache", {"Tours, France": [47.39, 0.68]})

    geocoder._save_cache()
    monkeypatch.setattr(geocoder, "_cache", {})
    geocoder._load_cache()

    assert geocoder._cache == {"Tours, France": [47.39, 0.68]}


def test_load_cache_leaves_cache_empty_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(geocoder, "CACHE_FILE", str(tmp_path / "missing.json"))
    monkeypatch.setattr(geocoder, "_cache", {"stale": [1.0, 2.0]})

    geocoder._load_cache()

    assert geocoder._cache == {"stale": [1.0, 2.0]}  # untouched, not reset


# ─── network error handling ─────────────────────────────────────────────────

def test_nominatim_query_returns_none_on_request_exception(monkeypatch):
    monkeypatch.setattr(geocoder, "_last_request", 0.0)
    monkeypatch.setattr(geocoder.time, "sleep", lambda *_: None)

    def fake_get(*a, **k):
        raise requests.exceptions.Timeout("boom")

    monkeypatch.setattr(geocoder.requests, "get", fake_get)

    assert geocoder._nominatim_query("Nulle Part") is None


def test_nominatim_query_throttles_consecutive_requests(monkeypatch):
    """No more than ~1 request/second to Nominatim, per its usage policy."""
    monkeypatch.setattr(geocoder, "_last_request", time.time())

    slept = []
    monkeypatch.setattr(geocoder.time, "sleep", lambda s: slept.append(s))

    class Resp:
        def json(self):
            return []

    monkeypatch.setattr(geocoder.requests, "get", lambda *a, **k: Resp())

    geocoder._nominatim_query("Tours")

    assert slept and slept[0] > 0


def test_ban_query_returns_none_on_request_exception(monkeypatch):
    def fake_get(*a, **k):
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(geocoder.requests, "get", fake_get)

    assert geocoder._ban_query("Tours") is None
