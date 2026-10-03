"""
Snapshot na demo: data/seed_events.json (eksport `python -m m2_scraper.run --source all --export data/seed_events.json`).

Działa bez internetu — eventy mają już ID, źródło i współrzędne. Wydarzenia zakończone przed dzisiaj są
pomijane, żeby mapa na demo pokazywała tylko aktualne pinezki.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from m2_scraper.sources.manual_json import ManualJsonSource
from shared.models import Event
from shared.storage import PROJECT_ROOT

SEED_PATH = PROJECT_ROOT / "data" / "seed_events.json"


class SeedSource(ManualJsonSource):
    name = "seed"

    def __init__(self, path: str | Path = SEED_PATH, today: date | None = None):
        super().__init__(path)
        self.today = today

    def fetch(self) -> list[Event]:
        day_start = datetime.combine(self.today or date.today(), datetime.min.time())
        return [e for e in super().fetch() if e.end_or_start >= day_start]
