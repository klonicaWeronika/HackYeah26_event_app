"""
M2 — pipeline zasilania bazy:  źródło.fetch() -> filtr Krakowa -> deduplikacja -> storage.upsert_events().

    python -m m2_scraper.run --source karnet --dry-run
    python -m m2_scraper.run --source all              # wszystkie scrapery (sieć / cache HTML)
    python -m m2_scraper.run --source manual

Działa równolegle z uruchomioną aplikacją: Storage w aplikacji wykryje zmianę
(PRAGMA data_version) i przy następnym rerunie pokaże nowe pinezki.
"""

from __future__ import annotations

import argparse
import logging

from m2_scraper.base import EventSource
from m2_scraper.dedupe import dedupe
from m2_scraper.sources import SCRAPERS, SOURCES
from shared.models import Event, is_in_krakow
from shared.storage import Storage, get_storage

log = logging.getLogger(__name__)


def collect(source: EventSource) -> list[Event]:
    """Pobiera eventy ze źródła, odrzuca te spoza Krakowa i duplikaty ID. Błąd źródła != awaria pipeline."""
    try:
        events = source.fetch()
    except Exception:  # noqa: BLE001 — jedno padnięte źródło nie może zatrzymać pozostałych
        log.exception("Źródło %s nie zadziałało", source.name)
        return []
    kept = [e for e in events if is_in_krakow(e.lat, e.lon)]
    if len(kept) < len(events):
        log.warning("%s: odrzucono %d eventów spoza Krakowa", source.name, len(events) - len(kept))
    return list({e.id: e for e in kept}.values())


def run(source_names: list[str], storage: Storage | None = None, *, dry_run: bool = False) -> int:
    """Zbiera eventy ze wszystkich źródeł, usuwa duplikaty (także względem bazy) i zapisuje. Zwraca liczbę."""
    collected: list[Event] = []
    for name in source_names:
        events = collect(SOURCES[name]())
        log.info("%s: %d eventów", name, len(events))
        collected.extend(events)

    store = storage if storage is not None else (None if dry_run else get_storage())
    run_sources = {e.source for e in collected}
    # eventy z innych źródeł już w bazie (np. wcześniejszy `--source opera`): ich duplikatów nie dopisujemy
    existing = [e for e in store.list_events() if e.source not in run_sources and e.source != "mock"] \
        if store is not None else []
    events = dedupe(collected, existing)
    if len(events) < len(collected):
        log.info("Deduplikacja: pominięto %d duplikatów", len(collected) - len(events))
    if not dry_run and events:
        store.upsert_events(events)
    return len(events)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Zasilanie bazy wydarzeniami")
    parser.add_argument("--source", default="all", choices=["all", *SOURCES],
                        help=f"'all' = wszystkie scrapery ({', '.join(SCRAPERS)})")
    parser.add_argument("--dry-run", action="store_true", help="tylko pobierz i zwaliduj, nie zapisuj")
    args = parser.parse_args()

    names = list(SCRAPERS) if args.source == "all" else [args.source]
    count = run(names, dry_run=args.dry_run)
    print(f"{'[dry-run] ' if args.dry_run else ''}Przetworzono {count} eventów ze źródeł: {', '.join(names)}")
