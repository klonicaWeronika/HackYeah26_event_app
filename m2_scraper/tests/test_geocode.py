"""M2-04 — geokodowanie: słownik -> cache -> Nominatim (bramkowany robots.txt), offline z udawanym HTTP."""

import json
from urllib.parse import parse_qs, urlsplit

from m2_scraper.geocode import Geocoder, geocode, known_venue, nominatim_url
from m2_scraper.tests.conftest import FakeGeoHttp
from shared.mock_data import KRAKOW_VENUES

GROTESKA = (50.06324, 19.92652)          # z m2_scraper/venues.py
NCK_QUERY = "al. Jana Pawła II 232, Kraków"


def test_known_venues_from_shared_and_extra_dictionary():
    assert geocode("Filharmonia Krakowska") == (KRAKOW_VENUES["filharmonia"].lat, KRAKOW_VENUES["filharmonia"].lon)
    assert geocode("teatr groteska") == GROTESKA                     # venues.py, bez wielkości liter
    assert geocode("Kino Kijów Centrum") == (KRAKOW_VENUES["kijow"].lat, KRAKOW_VENUES["kijow"].lon)
    assert known_venue("Kino") is None                               # za krótkie na dopasowanie częściowe
    assert geocode("") is None and geocode("   ", "") is None


def test_nominatim_skipped_when_robots_disallow(tmp_path):
    http = FakeGeoHttp({NCK_QUERY: [(50.07, 20.03)]}, allowed=False)
    geo = Geocoder(tmp_path / "geo.json", http=http)
    assert geo.geocode("Jakieś Nowe Miejsce", "al. Jana Pawła II 232, Kraków") is None
    assert http.queries == []                                        # zero zapytań
    assert not (tmp_path / "geo.json").exists()                      # brak zapisu -> spróbujemy, gdy robots zmieni


def test_nominatim_result_is_cached_and_second_run_is_offline(tmp_path):
    http = FakeGeoHttp({NCK_QUERY: [(50.07036, 20.03503)]}, allowed=True)
    geo = Geocoder(tmp_path / "geo.json", http=http)
    assert geo.geocode("Jakieś Nowe Miejsce", "al. Jana Pawła II 232, Kraków") == (50.07036, 20.03503)
    assert http.queries == [NCK_QUERY]

    second_http = FakeGeoHttp({}, allowed=True)                      # nowy proces: tylko cache z dysku
    again = Geocoder(tmp_path / "geo.json", http=second_http)
    assert again.geocode("Jakieś Nowe Miejsce", "al. Jana Pawła II 232, Kraków") == (50.07036, 20.03503)
    assert second_http.queries == []


def test_empty_and_outside_krakow_results_are_cached_as_none(tmp_path):
    http = FakeGeoHttp({"Warszawska 1, Kraków": [(52.23, 21.01)]}, allowed=True)   # Warszawa, poza bbox
    geo = Geocoder(tmp_path / "geo.json", http=http)
    assert geo.geocode("Nieistniejące", "Warszawska 1, Kraków") is None
    assert http.queries == ["Warszawska 1, Kraków", "Nieistniejące, Kraków"]       # adres, potem nazwa
    assert geo.geocode("Nieistniejące", "Warszawska 1, Kraków") is None
    assert len(http.queries) == 2                                    # pusty wynik też z cache
    assert json.loads((tmp_path / "geo.json").read_text(encoding="utf-8")) == {"nieistniejace|warszawska 1, krakow": None}


def test_network_error_is_not_cached(tmp_path):
    geo = Geocoder(tmp_path / "geo.json", http=FakeGeoHttp({}, allowed=True, fail=True))
    assert geo.geocode("Nowe", "ul. Nowa 1") is None
    assert not (tmp_path / "geo.json").exists()


def test_nominatim_url_follows_usage_policy():
    params = parse_qs(urlsplit(nominatim_url("Rynek Główny 1, Kraków")).query)
    assert params["countrycodes"] == ["pl"] and params["bounded"] == ["1"] and params["limit"] == ["1"]
    assert params["viewbox"] == ["19.78,50.13,20.22,49.96"]        # lon_min,lat_max,lon_max,lat_min
    assert params["format"] == ["jsonv2"]
