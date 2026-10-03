"""
Źródło uzupełniające: Opera Krakowska — repertuar z publicznego endpointu JSON strony + strony spektakli.

    GET /ajax/repertuar?year=2026&month=10   (to samo, co pobiera kalendarz na opera.krakow.pl/repertuar)
    GET /spektakle/<slug>                     (cennik, kompozytor, czas trwania, obrazek)

Odpowiedź JSON bywa otoczona wstrzykniętym <script> (Cloudflare) — parsujemy od pierwszego "{".
Obsady i realizatorów nie kopiujemy (opis = gatunek · kompozytor · scena · czas trwania).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from pydantic import ValidationError

from m2_scraper.base import PoliteHttp
from m2_scraper.normalize import clean_text, extract_tags, map_category, parse_price
from shared.mock_data import KRAKOW_VENUES
from shared.models import Category, Event, stable_id

log = logging.getLogger(__name__)

BASE_URL = "https://opera.krakow.pl"
REPERTOIRE_URL = BASE_URL + "/ajax/repertuar?year={year}&month={month}"
LIST_TTL_S = 6 * 3600
DETAIL_TTL_S = 3 * 24 * 3600
VENUE = KRAKOW_VENUES["opera"]


@dataclass(frozen=True)
class OperaPerformance:
    title: str
    type: str                   # "Opera" | "Balet" | "Koncert" | "Warsztaty" | ...
    start: datetime
    stage: str                  # "Duża Scena"
    url: str                    # strona spektaklu
    ticket_url: str | None
    canceled: bool


@dataclass(frozen=True)
class OperaSpectacle:
    price_pln: float | None
    composer: str
    duration: str
    image_url: str | None


def _json_from(payload: str) -> dict:
    start = payload.find("{")
    if start < 0:
        return {}
    data, _ = json.JSONDecoder().raw_decode(payload[start:])
    return data


def parse_repertoire(payload: str) -> list[OperaPerformance]:
    data = _json_from(payload)
    base_route = data.get("baseRoute") or "/spektakle"
    out: list[OperaPerformance] = []
    for item in data.get("performances") or []:
        perf = item.get("0") or {}
        try:
            day = perf["date"]["date"][:10]
            hhmm = perf["time"]["date"][11:16]
            start = datetime.fromisoformat(f"{day}T{hhmm}")
        except (KeyError, TypeError, ValueError):
            continue
        out.append(OperaPerformance(
            title=clean_text(item.get("title") or ""), type=clean_text(item.get("type") or ""), start=start,
            stage=clean_text(item.get("place") or ""),
            url=urljoin(BASE_URL + "/", f"{base_route.strip('/')}/{item.get('slug', '')}"),
            ticket_url=perf.get("ticketUrl") or item.get("ticketUrl"), canceled=bool(perf.get("isCanceled")),
        ))
    return out


def parse_spectacle(html: str) -> OperaSpectacle:
    soup = BeautifulSoup(html, "html.parser")
    prices = [p for p in (parse_price(el.get_text(" ", strip=True))
                          for el in soup.select(".price-list__list__item__price")) if p is not None]
    info = {}
    for block in soup.select(".detail-info"):
        title = block.select_one(".detail-info__title")
        text = block.select_one(".detail-info__text")
        if title and text:
            info[clean_text(title.get_text(" ", strip=True)).lower()] = clean_text(text.get_text(" ", strip=True))
    img = soup.select_one(".header-spectatle img")
    src = (img.get("src") or img.get("data-src")) if img else None
    return OperaSpectacle(
        price_pln=min(prices) if prices else None,                       # "od ..." = najtańsza kategoria
        composer=info.get("kompozytor", ""), duration=info.get("czas trwania", "").replace(" |", ","),
        image_url=urljoin(BASE_URL + "/", src) if src else None,
    )


def build_events(perfs: list[OperaPerformance], spectacles: dict[str, OperaSpectacle], today: date,
                 horizon: date, source_name: str = "opera") -> list[Event]:
    day_start = datetime.combine(today, datetime.min.time())
    out: list[Event] = []
    for perf in perfs:
        if perf.canceled or perf.start < day_start or perf.start.date() > horizon or not perf.title:
            continue
        spec = spectacles.get(perf.url)
        parts = [perf.type, spec.composer if spec else "", f"{perf.stage} Opery Krakowskiej" if perf.stage else "",
                 f"czas trwania: {spec.duration}" if spec and spec.duration else ""]
        description = " · ".join(p for p in parts if p)
        category = map_category(perf.type, perf.title, description)
        tags = extract_tags(f"{perf.title} {description}", source_type=perf.type)
        if category == Category.MUSIC and not tags:
            tags = ["klasyka"]                                          # koncerty w operze = muzyka klasyczna
        try:
            out.append(Event(
                id=stable_id("ev", source_name, f"{perf.url}#{perf.start:%Y-%m-%dT%H:%M}"),
                title=perf.title, description=description, category=category, tags=tags, start=perf.start,
                venue=VENUE.name + (f" — {perf.stage}" if perf.stage else ""),
                address=f"{VENUE.address}, Kraków", lat=VENUE.lat, lon=VENUE.lon,
                price_pln=spec.price_pln if spec else None, url=perf.url,
                image_url=spec.image_url if spec else None, source=f"scraper:{source_name}",
            ))
        except ValidationError as exc:
            log.warning("Opera: niepoprawny event %r: %s", perf.title, exc.errors()[:1])
    return out


def _months(today: date, horizon: date) -> list[tuple[int, int]]:
    months, cursor = [], date(today.year, today.month, 1)
    while cursor <= horizon:
        months.append((cursor.year, cursor.month))
        cursor = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
    return months


class OperaSource:
    name = "opera"

    def __init__(self, http: PoliteHttp | None = None, *, days: int = 30, today: date | None = None):
        self.http = http or PoliteHttp(delay_s=1.5)
        self.days = days
        self.today = today

    def fetch(self) -> list[Event]:
        today = self.today or date.today()
        horizon = today + timedelta(days=self.days)
        perfs: list[OperaPerformance] = []
        for year, month in _months(today, horizon):
            perfs.extend(parse_repertoire(self.http.get_text(REPERTOIRE_URL.format(year=year, month=month),
                                                             LIST_TTL_S)))
        perfs = list({(p.url, p.start): p for p in perfs}.values())     # ten sam spektakl w dwóch odpowiedziach
        spectacles: dict[str, OperaSpectacle] = {}
        for url in dict.fromkeys(p.url for p in perfs if p.start.date() <= horizon):
            try:
                spectacles[url] = parse_spectacle(self.http.get_text(url, DETAIL_TTL_S))
            except Exception as exc:  # noqa: BLE001 — brak szczegółów = event bez ceny, nie błąd źródła
                log.warning("Opera: nie udało się pobrać %s: %s", url, exc)
        return build_events(perfs, spectacles, today, horizon, self.name)
