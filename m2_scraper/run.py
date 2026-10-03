"""
M2 — pipeline zasilania bazy:  źródło.fetch() -> filtr Krakowa -> deduplikacja -> storage.upsert_events().

    python -m m2_scraper.run --source karnet --dry-run
    python -m m2_scraper.run --source all              # wszystkie scrapery (sieć / cache HTML)
    python -m m2_scraper.run --source all --days 7     # tylko najbliższe 7 dni
    python -m m2_scraper.run --source all --export data/seed_events.json   # snapshot na demo
    python -m m2_scraper.run --source seed             # demo offline: snapshot -> baza

Po każdym uruchomieniu drukuje raport jakości (bez geo / ceny / opisu / tagów, kategorie).
Działa równolegle z uruchomioną aplikacją: Storage w aplikacji wykryje zmianę
(PRAGMA data_version) i przy następnym rerunie pokaże nowe pinezki.
"""

from __future__ import annotations

import argparse
import inspect
import json
import logging
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from m2_scraper.base import EventSource
from m2_scraper.dedupe import dedupe
from m2_scraper.report import quality_report
from m2_scraper.sources import SCRAPERS, SOURCES
from shared.models import Event, is_in_krakow
from shared.storage import Storage, get_storage

log = logging.getLogger(__name__)


def collect(source: EventSource, dropped: Counter | None = None) -> list[Event]:
    """Pobiera eventy ze źródła, odrzuca te spoza Krakowa i duplikaty ID. Błąd źródła != awaria pipeline.

    `dropped` (opcjonalnie) dostaje liczniki odrzuconych eventów: powód -> liczba.
    """
    try:
        events = source.fetch()
    except Exception:  # noqa: BLE001 — jedno padnięte źródło nie może zatrzymać pozostałych
        log.exception("Źródło %s nie zadziałało", source.name)
        if dropped is not None:
            dropped["błąd źródła"] += 1
        return []
    kept = [e for e in events if is_in_krakow(e.lat, e.lon)]
    if len(kept) < len(events):
        log.warning("%s: odrzucono %d eventów spoza Krakowa", source.name, len(events) - len(kept))
    if dropped is not None:
        dropped.update(getattr(source, "dropped", None) or {})
        if len(kept) < len(events):
            dropped["poza Krakowem"] += len(events) - len(kept)
    return list({e.id: e for e in kept}.values())


def make_source(name: str, days: int | None = None) -> EventSource:
    """Instancja źródła; scrapery z parametrem `days` dostają horyzont (krótszy crawl)."""
    cls = SOURCES[name]
    if days is not None and "days" in inspect.signature(cls).parameters:
        return cls(days=days)
    return cls()


def within_days(events: list[Event], days: int, today: date | None = None) -> list[Event]:
    """Eventy trwające w [dziś, dziś + days] (wystawa trwająca od miesiąca też się łapie)."""
    day_start = datetime.combine(today or date.today(), datetime.min.time())
    horizon = day_start.date() + timedelta(days=days)
    return [e for e in events if e.end_or_start >= day_start and e.start.date() <= horizon]


def export_events(events: list[Event], path: str | Path) -> None:
    """Snapshot do JSON (lista obiektów Event) — wczytywany offline przez źródło "seed"."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [e.model_dump(mode="json") for e in sorted(events, key=lambda e: (e.start, e.id))]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def run(source_names: list[str], storage: Storage | None = None, *, dry_run: bool = False,
        export: str | Path | None = None, days: int | None = None, report: bool = True) -> int:
    """Zbiera eventy ze wszystkich źródeł, usuwa duplikaty (także względem bazy) i zapisuje. Zwraca liczbę.

    `export` = ścieżka snapshotu JSON (zapisywany także przy dry_run); `days` = tylko najbliższe N dni.
    """
    collected: list[Event] = []
    dropped: dict[str, Counter] = {}
    for name in source_names:
        dropped[name] = Counter()
        events = collect(make_source(name, days), dropped[name])
        log.info("%s: %d eventów", name, len(events))
        collected.extend(events)
    if days is not None:
        collected = within_days(collected, days)

    store = storage if storage is not None else (None if dry_run else get_storage())
    run_sources = {e.source for e in collected}
    # eventy z innych źródeł już w bazie (np. wcześniejszy `--source opera`): ich duplikatów nie dopisujemy
    existing = [e for e in store.list_events() if e.source not in run_sources and e.source != "mock"] \
        if store is not None else []
    events = dedupe(collected, existing)
    if len(events) < len(collected):
        log.info("Deduplikacja: pominięto %d duplikatów", len(collected) - len(events))
    if export:
        export_events(events, export)
        log.info("Snapshot: %d eventów -> %s", len(events), export)
    if not dry_run and events:
        store.upsert_events(events)
    if report:
        print(quality_report(events, {k: v for k, v in dropped.items() if v}))
    return len(events)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Zasilanie bazy wydarzeniami")
    parser.add_argument("--source", default="all", choices=["all", *SOURCES],
                        help=f"'all' = wszystkie scrapery ({', '.join(SCRAPERS)})")
    parser.add_argument("--dry-run", action="store_true", help="tylko pobierz i zwaliduj, nie zapisuj do bazy")
    parser.add_argument("--export", metavar="PATH", help="zapisz snapshot JSON (np. data/seed_events.json)")
    parser.add_argument("--days", type=int, metavar="N", help="tylko wydarzenia z najbliższych N dni")
    args = parser.parse_args()

    names = list(SCRAPERS) if args.source == "all" else [args.source]
    count = run(names, dry_run=args.dry_run, export=args.export, days=args.days)
    print(f"{'[dry-run] ' if args.dry_run else ''}Przetworzono {count} eventów ze źródeł: {', '.join(names)}")
