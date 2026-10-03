"""M2-06 — snapshot na demo: eksport -> źródło "seed" -> baza, całkowicie offline."""

import json
from datetime import date, datetime

from m2_scraper import run as run_module
from m2_scraper.run import export_events, run
from m2_scraper.sources.seed import SEED_PATH, SeedSource
from shared.mock_data import KRAKOW_VENUES
from shared.models import Category, Event, stable_id
from shared.storage import Storage

ALCHEMIA = KRAKOW_VENUES["alchemia"]
TODAY = date(2026, 10, 3)


def _event(title: str, start: datetime, end: datetime | None = None) -> Event:
    url = f"https://karnet.example/{title}"
    return Event(id=stable_id("ev", "karnet", url), title=title, start=start, end=end, venue=ALCHEMIA.name,
                 address=ALCHEMIA.address, lat=ALCHEMIA.lat, lon=ALCHEMIA.lon, url=url, price_pln=20,
                 category=Category.MUSIC, tags=["jazz"], description="Opis", source="scraper:karnet")


EVENTS = [
    _event("Jazz dziś", datetime(2026, 10, 3, 20, 0)),
    _event("Wystawa trwa", datetime(2026, 9, 1), datetime(2026, 12, 31, 23, 59)),    # zaczęła się wcześniej
    _event("Wczorajszy koncert", datetime(2026, 10, 2, 19, 0)),                       # już po -> pomijany
]


def test_export_and_seed_roundtrip_preserves_events(tmp_path):
    path = tmp_path / "seed.json"
    export_events(EVENTS, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert [r["title"] for r in raw] == ["Wystawa trwa", "Wczorajszy koncert", "Jazz dziś"]   # po starcie
    loaded = SeedSource(path, today=TODAY).fetch()
    assert {e.title for e in loaded} == {"Jazz dziś", "Wystawa trwa"}
    original = {e.id: e for e in EVENTS}
    assert all(e == original[e.id] for e in loaded)                  # ID, źródło, tagi, cena — bez zmian


def test_seed_into_empty_database_offline(empty_storage: Storage, tmp_path, monkeypatch):
    path = tmp_path / "seed.json"
    export_events(EVENTS, path)
    monkeypatch.setitem(run_module.SOURCES, "seed", lambda: SeedSource(path, today=TODAY))
    assert run(["seed"], storage=empty_storage) == 2                 # sieć zablokowana w conftest
    assert run(["seed"], storage=empty_storage) == 2
    assert empty_storage.stats()["events"] == 2


def test_export_during_dry_run_does_not_touch_db(empty_storage: Storage, tmp_path):
    out = tmp_path / "snap.json"
    assert run(["manual"], storage=empty_storage, dry_run=True, export=out) == 2
    assert empty_storage.stats()["events"] == 0 and len(json.loads(out.read_text(encoding="utf-8"))) == 2


def test_new_file_database_autoloads_snapshot_and_reset_reloads(tmp_path):
    """Świeży klon: pusta baza plikowa = mocki + prawdziwe eventy M2, bez scrapowania i bez sieci."""
    from shared.mock_data import build_mock_dataset

    mocks = len(build_mock_dataset().events)
    real = len(SeedSource(SEED_PATH).fetch())                        # ten sam filtr "nie zakończone"
    store = Storage(tmp_path / "app.db")
    try:
        events = store.list_events()
        assert sum(e.source == "mock" for e in events) == mocks
        assert sum(e.source.startswith("scraper:") for e in events) == real
        store.reset()
        assert store.stats()["events"] == mocks + real
        store.reset(seed=False)
        assert store.stats()["events"] == 0
    finally:
        store.close()


def test_memory_database_stays_mock_only(storage: Storage):
    assert {e.source for e in storage.list_events()} == {"mock"}    # testy innych modułów bez zmian


def test_seed_real_events_without_snapshot_file(empty_storage: Storage, tmp_path):
    assert empty_storage.seed_real_events(tmp_path / "brak.json") == 0


def test_committed_snapshot_is_valid_and_rich():
    """Plik w repo (demo offline): poprawne eventy z Krakowa, kilka kategorii, większość z tagami."""
    events = SeedSource(SEED_PATH, today=date(2000, 1, 1)).fetch()   # bez filtra dat
    assert len(events) >= 50
    assert len({e.category for e in events}) >= 5
    assert sum(bool(e.tags) for e in events) >= 0.9 * len(events)
    assert all(e.source.startswith("scraper:") for e in events)
    assert len({e.id for e in events}) == len(events)
