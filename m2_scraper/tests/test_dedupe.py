"""M2-05 — deduplikacja: po ID w źródle, heurystyka między źródłami, brak duplikatów po ponownym uruchomieniu."""

from datetime import datetime

import pytest

from m2_scraper import run as run_module
from m2_scraper.dedupe import dedupe, is_duplicate, titles_similar
from m2_scraper.run import run
from shared.mock_data import KRAKOW_VENUES
from shared.models import Category, Event, stable_id
from shared.storage import Storage

OPERA = KRAKOW_VENUES["opera"]
STUDIO = KRAKOW_VENUES["studio"]


def ev(source: str, title: str, start: datetime, venue=OPERA, url: str | None = None, **kw) -> Event:
    url = url or f"https://{source}.example/{title}/{start:%Y%m%d%H%M}"
    return Event(id=stable_id("ev", source, url), title=title, start=start, venue=venue.name,
                 lat=venue.lat, lon=venue.lon, url=url, source=f"scraper:{source}", category=Category.MUSIC, **kw)


FAUST_KARNET = ev("karnet", "Faust (Opera Krakowska)", datetime(2026, 10, 16, 18, 30), price_pln=90, description="x")
FAUST_OPERA = ev("opera", "Faust", datetime(2026, 10, 16, 18, 30))


@pytest.mark.parametrize("a, b, expected", [
    ("Faust", "Faust (Opera Krakowska)", True),                      # tokeny jednego ⊆ drugiego
    ("SBB (Skrzek, Anthimos, Piotrowski) w Studio", "SBB w Studio", True),
    ("Mrozu: Odpowiedni moment w Tauron Arenie Kraków", "Mrozu", True),
    ("Requiem", "Faust", False),
    ("Koncert", "Koncert", False),                                   # same słowa pomijane -> brak treści
])
def test_titles_similar(a, b, expected):
    assert titles_similar(a, b) is expected


def test_cross_source_duplicate_keeps_richer_source():
    kept = dedupe([FAUST_OPERA, FAUST_KARNET])
    assert kept == [FAUST_KARNET]                                    # Karnet: cena + opis


def test_not_duplicate_when_time_place_or_title_differ():
    assert not is_duplicate(FAUST_KARNET, ev("opera", "Faust", datetime(2026, 10, 17, 18, 30)))   # inny dzień
    assert not is_duplicate(FAUST_KARNET, ev("opera", "Faust", datetime(2026, 10, 16, 11, 0)))    # inna godzina
    assert not is_duplicate(FAUST_KARNET, ev("opera", "Faust", datetime(2026, 10, 16, 18, 30), venue=STUDIO))
    assert not is_duplicate(FAUST_KARNET, ev("opera", "Requiem", datetime(2026, 10, 16, 18, 30)))
    # brak godziny w jednym źródle (00:00) nie wyklucza duplikatu
    assert is_duplicate(FAUST_KARNET, ev("opera", "Faust", datetime(2026, 10, 16)))


def test_same_id_is_collapsed_and_existing_duplicates_are_skipped():
    assert len(dedupe([FAUST_KARNET, FAUST_KARNET])) == 1
    # Faust z Opery jest już w bazie (wcześniejsze uruchomienie innego źródła) -> Karnet go nie dubluje
    assert dedupe([FAUST_KARNET], existing=[FAUST_OPERA]) == []
    # ...ale aktualizacja eventu o tym samym ID przechodzi
    assert dedupe([FAUST_OPERA], existing=[FAUST_OPERA]) == [FAUST_OPERA]


class _StaticSource:
    def __init__(self, name: str, events: list[Event]):
        self.name, self._events = name, events

    def fetch(self) -> list[Event]:
        return self._events


def test_pipeline_twice_and_across_sources_creates_no_duplicates(empty_storage: Storage, monkeypatch):
    monkeypatch.setitem(run_module.SOURCES, "karnet", lambda: _StaticSource("karnet", [FAUST_KARNET]))
    monkeypatch.setitem(run_module.SOURCES, "opera", lambda: _StaticSource("opera", [FAUST_OPERA]))
    assert run(["karnet", "opera"], storage=empty_storage) == 1
    assert run(["karnet", "opera"], storage=empty_storage) == 1
    assert run(["opera"], storage=empty_storage) == 0                # Faust z Karnetu już jest w bazie
    assert [e.id for e in empty_storage.list_events()] == [FAUST_KARNET.id]
