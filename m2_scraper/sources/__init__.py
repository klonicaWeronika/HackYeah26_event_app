"""Rejestr źródeł wydarzeń. Nowe źródło = nowy plik + wpis w SOURCES.

Kolejność ma znaczenie: pierwszy wpis jest domyślny w sandboxie (smoke test) — musi działać offline.
"""

from __future__ import annotations

from m2_scraper.base import EventSource
from m2_scraper.sources.karnet import KarnetSource
from m2_scraper.sources.manual_json import ManualJsonSource
from m2_scraper.sources.mock_source import MockSource
from m2_scraper.sources.opera import OperaSource
from m2_scraper.sources.seed import SeedSource
from m2_scraper.sources.tauron import TauronSource

SOURCES: dict[str, type[EventSource]] = {
    "mock": MockSource,
    "manual": ManualJsonSource,
    "seed": SeedSource,             # snapshot data/seed_events.json — demo offline
    "karnet": KarnetSource,
    "opera": OperaSource,
    "tauron": TauronSource,
}

# Prawdziwe scrapery (sieć / cache HTML) — to uruchamia `--source all`. Kolejność = priorytet przy duplikatach.
SCRAPERS: list[str] = ["karnet", "opera", "tauron"]
