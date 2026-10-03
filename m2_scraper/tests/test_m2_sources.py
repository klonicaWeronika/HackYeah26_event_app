"""M2 — testy źródeł i pipeline'u (offline: mocki + fixture JSON)."""

from m2_scraper.geocode import geocode
from m2_scraper.run import run
from m2_scraper.sources.manual_json import ManualJsonSource
from m2_scraper.sources.mock_source import MockSource
from shared.models import is_in_krakow
from shared.storage import Storage


def test_mock_source_returns_valid_krakow_events():
    events = MockSource().fetch()
    assert events and all(is_in_krakow(e.lat, e.lon) for e in events)


def test_manual_json_source_geocodes_missing_coords():
    events = ManualJsonSource().fetch()
    assert len(events) == 2
    assert all(e.source == "scraper:manual" and e.id.startswith("ev_") for e in events)


def test_geocode_known_venue_and_unknown():
    assert geocode("Filharmonia Krakowska") is not None
    assert geocode("kino kijow") is not None                 # bez polskich znaków / wielkości liter
    assert geocode("") is None


def test_pipeline_upserts_into_storage(empty_storage: Storage):
    assert run(["manual"], storage=empty_storage) == 2
    assert empty_storage.stats()["events"] == 2
    run(["manual"], storage=empty_storage)                   # ponowne uruchomienie = brak duplikatów
    assert empty_storage.stats()["events"] == 2


def test_dry_run_does_not_write(empty_storage: Storage):
    run(["manual"], storage=empty_storage, dry_run=True)
    assert empty_storage.stats()["events"] == 0
