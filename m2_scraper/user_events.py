"""
M2-09 — logika formularza „Dodaj wydarzenie” (czyste funkcje, bez Streamlit — testowane w tests/).

Miejsce można wskazać na trzy sposoby: znane miejsce ze słownika, nazwa/adres (geokoder) albo klik na mapie.
Wynik: Event(source="user", created_by=user.id) gotowy do storage.upsert_event().
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from pydantic import ValidationError

from m2_scraper.geocode import geocode
from m2_scraper.normalize import extract_tags, with_city
from m2_scraper.venues import EXTRA_VENUES
from shared.mock_data import KRAKOW_VENUES
from shared.models import Category, Event, fold_text, is_in_krakow, new_id

TITLE_MIN, TITLE_MAX = 3, 120
DESCRIPTION_MAX = 600
MAX_TAGS = 8
PAST_TOLERANCE = timedelta(minutes=15)       # "zaczyna się teraz" nie jest błędem


class PlaceMode:
    KNOWN = "Znane miejsce"
    ADDRESS = "Nazwa i adres"
    MAP = "Wskaż na mapie"
    ALL = (KNOWN, ADDRESS, MAP)


@dataclass(frozen=True)
class Place:
    venue: str
    address: str
    lat: float
    lon: float


def known_places() -> dict[str, Place]:
    """Słownik miejsc do listy wyboru: KRAKOW_VENUES + m2_scraper/venues.py, posortowany po nazwie."""
    places: dict[str, Place] = {}
    for v in [*KRAKOW_VENUES.values(), *EXTRA_VENUES]:
        places.setdefault(v.name, Place(v.name, with_city(v.address), v.lat, v.lon))
    return dict(sorted(places.items(), key=lambda item: fold_text(item[0])))


def resolve_place(mode: str, *, known_name: str | None = None, venue_name: str = "", address: str = "",
                  picked: tuple[float, float] | None = None) -> tuple[Place | None, str | None]:
    """(miejsce, błąd). Miejsce zawsze w granicach Krakowa."""
    venue_name, address = (venue_name or "").strip(), (address or "").strip()
    if mode == PlaceMode.KNOWN:
        place = known_places().get(known_name or "")
        return (place, None) if place else (None, "Wybierz miejsce z listy.")
    if mode == PlaceMode.MAP:
        if picked is None:
            return None, "Kliknij na mapie, gdzie odbywa się wydarzenie."
        if not is_in_krakow(*picked):
            return None, "Wskazany punkt jest poza Krakowem."
        return Place(venue_name or "Miejsce wskazane na mapie", address, picked[0], picked[1]), None
    if not venue_name and not address:
        return None, "Podaj nazwę miejsca albo adres."
    coords = geocode(venue_name, address)
    if coords is None:
        return None, "Nie znaleźliśmy tego miejsca — wybierz je z listy albo wskaż na mapie."
    return Place(venue_name or address, with_city(address), coords[0], coords[1]), None


def build_user_event(
    user_id: str, *, title: str, category: Category | None, day: date | None, start_time: time | None,
    duration_h: float | None, place: Place | None, tags: list[str] | None = None, free: bool = False,
    price: float | None = None, description: str = "", url: str = "", now: datetime | None = None,
) -> tuple[Event | None, list[str]]:
    """Walidacja pól formularza -> (Event, []) albo (None, [komunikaty błędów po polsku])."""
    now = now or datetime.now()
    title, description, url = (title or "").strip(), (description or "").strip(), (url or "").strip()
    errors: list[str] = []
    if not TITLE_MIN <= len(title) <= TITLE_MAX:
        errors.append(f"Tytuł musi mieć od {TITLE_MIN} do {TITLE_MAX} znaków.")
    if category is None:
        errors.append("Wybierz kategorię.")
    start = datetime.combine(day, start_time) if day and start_time else None
    if start is None:
        errors.append("Podaj datę i godzinę rozpoczęcia.")
    elif start < now - PAST_TOLERANCE:
        errors.append("Wydarzenie nie może zaczynać się w przeszłości.")
    elif start > now + timedelta(days=366):
        errors.append("Wydarzenie może być najdalej za rok.")
    if duration_h is not None and not 0 < duration_h <= 24:
        errors.append("Czas trwania musi wynosić od 0,5 do 24 godzin.")
    if place is None:
        errors.append("Wskaż miejsce wydarzenia.")
    if len(description) > DESCRIPTION_MAX:
        errors.append(f"Opis może mieć najwyżej {DESCRIPTION_MAX} znaków.")
    if url and not url.startswith(("http://", "https://")):
        errors.append("Link musi zaczynać się od http:// lub https://.")
    if not free and price is not None and price < 0:
        errors.append("Cena nie może być ujemna.")
    if errors:
        return None, errors

    # brak tagów od użytkownika -> dobieramy ze słownika (matching M4 działa na tagach)
    final_tags = list(tags or [])[:MAX_TAGS] or extract_tags(f"{title} {description}")[:MAX_TAGS]
    try:
        event = Event(
            id=new_id("ev"), title=title, description=description, category=category, tags=final_tags,
            start=start, end=start + timedelta(hours=duration_h) if duration_h else None,
            venue=place.venue, address=place.address, lat=place.lat, lon=place.lon,
            price_pln=0.0 if free else price, url=url or None, source="user", created_by=user_id,
        )
    except ValidationError as exc:                               # zabezpieczenie: model jest źródłem prawdy
        return None, [f"Niepoprawne dane: {err['msg']}" for err in exc.errors()[:3]]
    return event, []
