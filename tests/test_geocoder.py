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
