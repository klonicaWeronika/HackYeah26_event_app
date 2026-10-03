"""
Źródło #1: Karnet — portal kulturalny Krakowskiego Biura Festiwalowego (karnet.krakowculture.pl).

Przepływ: lista `/wydarzenia?Item_page=N` (posortowana po dacie startu) -> karta (tytuł, typ, miejsce,
lat/lon, termin) -> strona szczegółów (wszystkie terminy, opis, cena, obrazek) -> Event na KAŻDY termin
w horyzoncie `days` (spektakl grany 3 razy = 3 eventy, bo na wspólne wyjście idzie się w konkretny dzień).

Parsery to czyste funkcje (html -> dataclass), testowane offline na m2_scraper/fixtures/karnet_*.html.
Decyzja o źródle i zasady etyczne: m2_scraper/README.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from m2_scraper.base import PoliteHttp
from m2_scraper.geocode import geocode
from m2_scraper.normalize import (
    DateSpan,
    clean_text,
    extract_tags,
    find_price,
    map_category,
    parse_pl_datetime,
    shorten,
)
from shared.models import Event, fold_text, is_in_krakow, stable_id

log = logging.getLogger(__name__)

BASE_URL = "https://karnet.krakowculture.pl"
LIST_URL = BASE_URL + "/wydarzenia?Item_page={page}"
LIST_TTL_S = 6 * 3600           # lista zmienia się w ciągu dnia
DETAIL_TTL_S = 3 * 24 * 3600    # szczegóły (terminy, cena) zmieniają się rzadko
SKIP_TYPES = {"w gminach metropolii"}   # miejscowości pod Krakowem (Wieliczka, Skawina...) — nie Kraków
_ADDRESS_PREFIXES = ("ul.", "al.", "pl.", "os.", "rynek", "plac", "aleja", "bulwar", "ulica", "skwer")


@dataclass(frozen=True)
class KarnetCard:
    """Surowe pola z karty na liście wydarzeń."""
    url: str
    title: str
    type: str
    lead: str
    location: str               # "Alchemia, ul. Estery 5"
    date_text: str              # "03.10.2026, 19:00" | "13.09.2026 - 13.11.2026"
    lat: float | None
    lon: float | None
    image_url: str | None = None


@dataclass(frozen=True)
class KarnetPlace:
    name: str
    address: str
    lat: float | None
    lon: float | None


@dataclass(frozen=True)
class KarnetDetail:
    """Surowe pola ze strony szczegółów."""
    title: str
    type: str
    dates: list[str]            # tylko nieprzeterminowane terminy
    dates_total: int            # łącznie z przeterminowanymi (stabilne ID przy wielu terminach)
    locations: list[str]
    places: list[KarnetPlace] = field(default_factory=list)
    description: str = ""
    info: str = ""              # blok "inne informacje" — zwykle ceny biletów
    ticket_url: str | None = None
    image_url: str | None = None


# --------------------------------------------------------------------------- #
# Parsery (czyste funkcje)
# --------------------------------------------------------------------------- #


def _text(node: Tag | None, sep: str = " ") -> str:
    return clean_text(node.get_text(sep, strip=True)) if node else ""


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def parse_listing(html: str, base_url: str = BASE_URL) -> tuple[list[KarnetCard], bool]:
    """Strona listy -> (karty, czy_jest_następna_strona)."""
    soup = BeautifulSoup(html, "html.parser")
    cards: list[KarnetCard] = []
    for item in soup.select("div.event-list > div.event-item"):
        link = item.select_one("a.event-content") or item.select_one("a[href]")
        if link is None:
            continue
        img = item.select_one("a.event-image img")
        cards.append(KarnetCard(
            url=urljoin(base_url + "/", link["href"]),
            title=clean_text(item.get("data-name") or _text(item.select_one(".event-title"))),
            type=_text(item.select_one(".event-type")),
            lead=_text(item.select_one(".event-text")),
            location=_text(item.select_one(".event-location")),
            date_text=_text(item.select_one(".event-date")),
            lat=_float(item.get("data-latitude")),
            lon=_float(item.get("data-longitude")),
            image_url=img.get("src") if img else None,
        ))
    has_next = any("następna" in a.get_text() for a in soup.select("a[href*='Item_page']"))
    return cards, has_next


def parse_detail(html: str) -> KarnetDetail:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one(".subpage-wrapper h1") or soup.find("h1")
    h4 = h1.find_next_sibling("h4") if h1 else None

    date_items = soup.select("li.event-date")
    dates = [_text(li.select_one(".label")) for li in date_items if "expired" not in (li.get("class") or [])]
    locations = [_text(li.select_one(".label")) for li in soup.select("ul.block-list li")
                 if li.select_one(".icon-location")]
    places = [
        KarnetPlace(
            name=clean_text(a.get("data-name") or _text(a.select_one("h3"))),
            address=_text(a.select_one(".data")),
            lat=_float(a.get("data-latitude")), lon=_float(a.get("data-longitude")),
        )
        for a in soup.select(".event-place a[data-latitude], .event-places a[data-latitude]")
    ]

    paragraphs: list[str] = []
    article = soup.select_one(".article-content")
    if article:
        for node in article.find_all(["p", "li", "h2", "h3"]):
            text = _text(node)
            if text and "materiały organizatora" not in text.lower():
                paragraphs.append(text)

    info = " ".join(_text(li.select_one(".label")) for li in soup.select(".article-more li")
                    if li.select_one(".icon-other-info"))
    ticket = next((a.get("href") for a in soup.select("a.button-big") if "bilet" in a.get_text().lower()), None)
    img = soup.select_one(".photo-slider img")
    return KarnetDetail(
        title=_text(h1), type=_text(h4), dates=dates, dates_total=len(date_items), locations=locations,
        places=places, description=" ".join(paragraphs), info=info, ticket_url=ticket,
        image_url=img.get("src") if img else None,
    )


def split_location(text: str) -> tuple[str, str]:
    """'Cricoteka, ul. Nadwiślańska 2' -> ('Cricoteka', 'ul. Nadwiślańska 2')."""
    venue, sep, address = (text or "").rpartition(", ")
    if sep and (address.lower().startswith(_ADDRESS_PREFIXES) or any(c.isdigit() for c in address)):
        return venue.strip(), address.strip()
    return (text or "").strip(), ""


# --------------------------------------------------------------------------- #
# Karta + szczegóły -> Event
# --------------------------------------------------------------------------- #


def _krakow_address(address: str) -> str:
    if address and "krakow" not in fold_text(address):
        return f"{address}, Kraków"
    return address


def _place(card: KarnetCard, detail: KarnetDetail | None) -> tuple[str, str, float, float] | None:
    """(venue, address, lat, lon) — najpierw blok 'Miejsce wydarzenia', potem karta, na końcu geokoder."""
    if detail:
        for place in detail.places:
            if place.lat is not None and place.lon is not None and is_in_krakow(place.lat, place.lon):
                return place.name, _krakow_address(place.address), place.lat, place.lon
    location = (detail.locations[0] if detail and detail.locations else "") or card.location
    venue, address = split_location(location)
    if card.lat is not None and card.lon is not None and is_in_krakow(card.lat, card.lon):
        return venue or "Kraków", _krakow_address(address), card.lat, card.lon
    coords = geocode(venue, address) if venue else None
    if coords is None:
        return None
    return venue, _krakow_address(address), coords[0], coords[1]


def build_events(card: KarnetCard, detail: KarnetDetail | None, today: date, horizon: date,
                 source_name: str = "karnet") -> list[Event]:
    """Jeden Event na każdy termin w [dziś, horyzont]. Bez miejsca na mapie -> brak eventu."""
    place = _place(card, detail)
    if place is None:
        log.warning("Karnet: brak współrzędnych, pomijam %s", card.url)
        return []
    venue, address, lat, lon = place

    date_texts = (detail.dates if detail and detail.dates_total else None) or [card.date_text]
    multi = (detail.dates_total if detail else 1) > 1
    day_start = datetime.combine(today, datetime.min.time())
    spans: list[DateSpan] = []
    for text in date_texts:
        span = parse_pl_datetime(text, today)
        if span is None:
            log.debug("Karnet: nieczytelny termin %r (%s)", text, card.url)
            continue
        if (span.end or span.start) >= day_start and span.start.date() <= horizon:
            spans.append(span)

    title = (detail.title if detail else "") or card.title
    source_type = (detail.type if detail else "") or card.type
    description = shorten((detail.description if detail else "") or card.lead)
    image_url = (detail.image_url if detail else None) or card.image_url
    # tagi i kategoria z tytułu + skróconego opisu: pełny opis daje za dużo przypadkowych słów kluczowych
    category = map_category(source_type, title, description)
    tags = extract_tags(f"{title} {description}", source_type=source_type)
    price = find_price(detail.info, detail.description) if detail else None

    events: list[Event] = []
    for span in sorted(set(spans), key=lambda s: s.start):
        id_key = f"{card.url}#{span.start:%Y-%m-%dT%H:%M}" if multi else card.url
        try:
            events.append(Event(
                id=stable_id("ev", source_name, id_key), title=title, description=description,
                category=category, tags=tags, start=span.start, end=span.end,
                venue=venue, address=address, lat=lat, lon=lon, price_pln=price,
                url=card.url, image_url=image_url, source=f"scraper:{source_name}",
            ))
        except ValidationError as exc:
            log.warning("Karnet: niepoprawny event %s: %s", card.url, exc.errors()[:1])
    return events


# --------------------------------------------------------------------------- #
# Źródło
# --------------------------------------------------------------------------- #


class KarnetSource:
    name = "karnet"

    def __init__(self, http: PoliteHttp | None = None, *, days: int = 30, today: date | None = None,
                 fetch_details: bool = True, max_pages: int = 150):
        self.http = http or PoliteHttp(delay_s=1.5)
        self.days = days
        self.today = today
        self.fetch_details = fetch_details
        self.max_pages = max_pages

    def crawl_listing(self, today: date, horizon: date) -> list[KarnetCard]:
        """Strony listy aż do pierwszej karty startującej po horyzoncie (lista jest posortowana po starcie)."""
        cards: dict[str, KarnetCard] = {}
        for page in range(1, self.max_pages + 1):
            page_cards, has_next = parse_listing(self.http.get_text(LIST_URL.format(page=page), LIST_TTL_S))
            beyond = False
            for card in page_cards:
                span = parse_pl_datetime(card.date_text, today)
                if span and span.start.date() > horizon:
                    beyond = True
                    continue
                cards.setdefault(card.url, card)        # przesunięcie stron w trakcie crawla -> duplikaty
            if beyond or not has_next or not page_cards:
                break
        return list(cards.values())

    def fetch(self) -> list[Event]:
        today = self.today or date.today()
        horizon = today + timedelta(days=self.days)
        events: list[Event] = []
        for card in self.crawl_listing(today, horizon):
            if fold_text(card.type) in SKIP_TYPES:
                continue
            detail = None
            if self.fetch_details:
                try:
                    detail = parse_detail(self.http.get_text(card.url, DETAIL_TTL_S))
                except Exception as exc:  # noqa: BLE001 — jedna zła strona nie zatrzymuje źródła
                    log.warning("Karnet: nie udało się pobrać szczegółów %s: %s", card.url, exc)
            events.extend(build_events(card, detail, today, horizon, self.name))
        return events
