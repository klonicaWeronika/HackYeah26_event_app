"""M2-08 — raport jakości w CLI i filtr --days."""

from collections import Counter
from datetime import date, datetime, time, timedelta

from m2_scraper import run as run_module
from m2_scraper.report import quality_report
from m2_scraper.run import collect, make_source, run, within_days
from m2_scraper.sources.karnet import KarnetSource
from m2_scraper.sources.mock_source import MockSource
from shared.mock_data import KRAKOW_VENUES
from shared.models import Category, Event, stable_id
from shared.storage import Storage

STUDIO = KRAKOW_VENUES["studio"]
TODAY = date.today()


def _ev(title: str, start: datetime, *, end=None, price=None, tags=(), desc="", lat=STUDIO.lat, lon=STUDIO.lon,
        source="karnet", category=Category.MUSIC) -> Event:
    return Event(id=stable_id("ev", source, title), title=title, start=start, end=end, venue=STUDIO.name,
                 lat=lat, lon=lon, price_pln=price, tags=list(tags), description=desc, category=category,
                 source=f"scraper:{source}")


def _day(offset: int, hour: int = 19) -> datetime:
    return datetime.combine(TODAY + timedelta(days=offset), time(hour, 0))


def test_quality_report_counts_per_source_and_total():
    events = [
        _ev("A", _day(0), price=20, tags=["jazz"], desc="opis"),
        _ev("B", _day(1), price=0, tags=["pop"]),                       # tag spoza INTEREST_TAGS
        _ev("C", _day(2), source="tauron", category=Category.SPORT),
    ]
    text = quality_report(events, {"karnet": Counter({"bez współrzędnych": 2})})
    assert "scraper:karnet      2 eventów" in text and "scraper:tauron      1 eventów" in text
    assert "RAZEM               3 eventów | bez ceny: 1 (33%) | darmowe: 1" in text
    assert "bez opisu: 2 (67%)" in text and "bez tagów: 1 (33%)" in text
    assert "bez tagu z INTEREST_TAGS: 2 (67%)" in text
    assert "odrzucone: bez współrzędnych 2" in text
    assert "kategorie (2): music 2, sport 1" in text


def test_within_days_keeps_ongoing_and_drops_past_or_far():
    events = [
        _ev("dziś", _day(0)),
        _ev("wystawa", _day(-20, 10), end=_day(20, 18)),                 # trwa -> zostaje
        _ev("za tydzień", _day(7)),
        _ev("wczoraj", _day(-1)),
    ]
    assert {e.title for e in within_days(events, 3)} == {"dziś", "wystawa"}
    assert {e.title for e in within_days(events, 7)} == {"dziś", "wystawa", "za tydzień"}


def test_make_source_passes_days_only_to_scrapers():
    assert isinstance(make_source("karnet", 3), KarnetSource) and make_source("karnet", 3).days == 3
    assert isinstance(make_source("mock", 3), MockSource)               # MockSource nie ma `days`


class _Source:
    name = "test"

    def __init__(self, events=None, fail=False):
        self._events, self._fail, self.dropped = events or [], fail, Counter({"bez współrzędnych": 1})

    def fetch(self):
        if self._fail:
            raise RuntimeError("strona nie działa")
        return self._events


def test_collect_counts_dropped_events():
    dropped = Counter()
    warsaw = _ev("Warszawa", _day(0), lat=52.23, lon=21.01)
    assert collect(_Source([_ev("A", _day(0)), warsaw]), dropped) == [_ev("A", _day(0))]
    assert dropped == Counter({"bez współrzędnych": 1, "poza Krakowem": 1})
    failed = Counter()
    assert collect(_Source(fail=True), failed) == [] and failed["błąd źródła"] == 1


def test_run_prints_report_and_applies_days(empty_storage: Storage, monkeypatch, capsys):
    events = [_ev("dziś", _day(0), tags=["jazz"]), _ev("za 10 dni", _day(10), tags=["rock"])]
    monkeypatch.setitem(run_module.SOURCES, "karnet", lambda **kw: _Source(events))
    assert run(["karnet"], storage=empty_storage, days=5) == 1
    out = capsys.readouterr().out
    assert "=== Raport jakości danych M2 ===" in out and "RAZEM               1 eventów" in out
    assert [e.title for e in empty_storage.list_events()] == ["dziś"]
