"""Rejestr źródeł wydarzeń. Nowe źródło = nowy plik + wpis w SOURCES."""

from __future__ import annotations

from m2_scraper.base import EventSource
from m2_scraper.sources.manual_json import ManualJsonSource
from m2_scraper.sources.mock_source import MockSource

SOURCES: dict[str, type[EventSource]] = {
    "mock": MockSource,
    "manual": ManualJsonSource,
    # "karnet": KarnetSource,   # TODO(M2)
}
