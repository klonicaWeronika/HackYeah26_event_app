"""
Źródło uzupełniające: TAURON Arena Kraków — publiczne REST API wtyczki The Events Calendar (WordPress).

    GET /wp-json/tribe/events/v1/events?per_page=50&page=N
Daje sport (półmaratony, koszykówka), duże koncerty i stand-up. Jedna lokalizacja (KRAKOW_VENUES["tauron"]).
"""

from __future__ import annotations

import html
import json
import logging
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup
from pydantic import ValidationError

from m2_scraper.base import PoliteHttp
from m2_scraper.normalize import clean_text, extract_tags, find_price, map_category, shorten
from shared.mock_data import KRAKOW_VENUES
from shared.models import Event, stable_id

log = logging.getLogger(__name__)

API_URL = "https://www.tauronarenakrakow.pl/wp-json/tribe/events/v1/events?per_page=50&page={page}"
LIST_TTL_S = 6 * 3600
VENUE = KRAKOW_VENUES["tauron"]


def _html_text(value: str) -> str:
    return clean_text(BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True))


def parse_events(payload: str, today: date, horizon: date, source_name: str = "tauron") -> list[Event]:
    """Odpowiedź API (JSON) -> eventy w [dziś, horyzont]."""
    data = json.loads(payload)
    day_start = datetime.combine(today, datetime.min.time())
    out: list[Event] = []
    for item in data.get("events", []):
        try:
            start = datetime.fromisoformat(item["start_date"])
            end = datetime.fromisoformat(item["end_date"]) if item.get("end_date") else None
        except (KeyError, ValueError):
            continue
        if (end or start) < day_start or start.date() > horizon:
            continue
        title = clean_text(html.unescape(item.get("title", "")))
        full_description = _html_text(item.get("description", ""))
        description = shorten(full_description)
        hall = _html_text(item.get("excerpt", ""))
        source_type = " ".join(c.get("name", "") for c in item.get("categories", []))
        # jak w Karnecie: tagi/kategoria z tytułu + skróconego opisu (długie teksty marketingowe = szum)
        category = map_category(source_type, title, description)
        tags = extract_tags(f"{title} {description}", source_type=source_type)
        price = find_price(item.get("cost", ""), full_description)
        url = item.get("url") or ""
        image = (item.get("image") or {}).get("url") if isinstance(item.get("image"), dict) else None
        try:
            out.append(Event(
                id=stable_id("ev", source_name, url or f"{title}|{start.isoformat()}"), title=title,
                description=description, category=category, tags=tags, start=start,
                end=end if end and end > start else None,
                venue=VENUE.name + (f" — {hall}" if hall and len(hall) < 40 else ""),
                address=f"{VENUE.address}, Kraków", lat=VENUE.lat, lon=VENUE.lon, price_pln=price,
                url=url or None, image_url=image, source=f"scraper:{source_name}",
            ))
        except ValidationError as exc:
            log.warning("Tauron: niepoprawny event %r: %s", title, exc.errors()[:1])
    return out


class TauronSource:
    name = "tauron"

    def __init__(self, http: PoliteHttp | None = None, *, days: int = 30, today: date | None = None,
                 max_pages: int = 5):
        self.http = http or PoliteHttp(delay_s=1.5)
        self.days = days
        self.today = today
        self.max_pages = max_pages

    def fetch(self) -> list[Event]:
        today = self.today or date.today()
        horizon = today + timedelta(days=self.days)
        events: list[Event] = []
        for page in range(1, self.max_pages + 1):
            payload = self.http.get_text(API_URL.format(page=page), LIST_TTL_S)
            events.extend(parse_events(payload, today, horizon, self.name))
            data = json.loads(payload)
            if page >= int(data.get("total_pages") or 1):
                break
        return events
