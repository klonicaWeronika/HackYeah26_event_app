"""
M2 — pipeline zasilania bazy:  źródło.fetch() -> walidacja/filtr Krakowa -> storage.upsert_events().

    python -m m2_scraper.run --source mock --dry-run
    python -m m2_scraper.run --source manual
    python -m m2_scraper.run --source all

Działa równolegle z uruchomioną aplikacją: Storage w aplikacji wykryje zmianę
(PRAGMA data_version) i przy następnym rerunie pokaże nowe pinezki.
"""

from __future__ import annotations

import argparse
import logging

from m2_scraper.base import EventSource
from m2_scraper.sources import SOURCES
from shared.models import Event, is_in_krakow
from shared.storage import Storage, get_storage

log = logging.getLogger(__name__)


def collect(source: EventSource) -> list[Event]:
    """Pobiera eventy ze źródła i odrzuca te spoza Krakowa. Błąd źródła != awaria całego pipeline."""
    try:
        events = source.fetch()
    except Exception:  # noqa: BLE001 — jedno padnięte źródło nie może zatrzymać pozostałych
        log.exception("Źródło %s nie zadziałało", source.name)
        return []
    kept = [e for e in events if is_in_krakow(e.lat, e.lon)]
    if len(kept) < len(events):
        log.warning("%s: odrzucono %d eventów spoza Krakowa", source.name, len(events) - len(kept))
    return kept


def run(source_names: list[str], storage: Storage | None = None, *, dry_run: bool = False) -> int:
    total = 0
    for name in source_names:
        events = collect(SOURCES[name]())
        log.info("%s: %d eventów", name, len(events))
        if not dry_run and events:
            (storage or get_storage()).upsert_events(events)
        total += len(events)
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Zasilanie bazy wydarzeniami")
    parser.add_argument("--source", default="all", choices=["all", *SOURCES])
    parser.add_argument("--dry-run", action="store_true", help="tylko pobierz i zwaliduj, nie zapisuj")
    args = parser.parse_args()

    names = list(SOURCES) if args.source == "all" else [args.source]
    count = run(names, dry_run=args.dry_run)
    print(f"{'[dry-run] ' if args.dry_run else ''}Przetworzono {count} eventów ze źródeł: {', '.join(names)}")
