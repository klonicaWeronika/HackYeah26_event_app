"""
Plan B dla scrapera: ręcznie zebrane wydarzenia w JSON (lista obiektów zgodnych z modelem Event).

Brakujące lat/lon są uzupełniane geokoderem; brakujące id -> stable_id ze źródła i tytułu.
Przykład formatu: m2_scraper/fixtures/manual_events.example.json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from m2_scraper.geocode import geocode
from shared.models import Event, stable_id
from shared.storage import PROJECT_ROOT

log = logging.getLogger(__name__)

DEFAULT_PATH = PROJECT_ROOT / "m2_scraper" / "fixtures" / "manual_events.example.json"


class ManualJsonSource:
    name = "manual"

    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path)

    def fetch(self) -> list[Event]:
        events: list[Event] = []
        for raw in json.loads(self.path.read_text(encoding="utf-8")):
            raw.setdefault("id", stable_id("ev", self.name, raw.get("title", ""), raw.get("start", "")))
            raw.setdefault("source", f"scraper:{self.name}")
            if "lat" not in raw or "lon" not in raw:
                coords = geocode(raw.get("venue", ""), raw.get("address", ""))
                if coords is None:
                    log.warning("Brak współrzędnych, pomijam: %s", raw.get("title"))
                    continue
                raw["lat"], raw["lon"] = coords
            try:
                events.append(Event.model_validate(raw))
            except ValidationError as exc:
                log.warning("Niepoprawny event %r: %s", raw.get("title"), exc.errors()[:1])
        return events
