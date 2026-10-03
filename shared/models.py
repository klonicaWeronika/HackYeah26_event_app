"""
shared/models.py — WSPÓLNY KONTRAKT DANYCH (single source of truth dla 5 modułów).

Zasady zmian w trakcie hackathonu:
  * Zmiany WYŁĄCZNIE addytywne: nowe pole = zawsze z wartością domyślną
    (stare rekordy w SQLite dalej się wczytają, `extra="ignore"` toleruje usunięte pola).
  * Zmiana nazwy/typu istniejącego pola = PR do Leada (łamie kilka modułów naraz).
  * Modele są NIEMUTOWALNE (frozen). Zmiana = `obj.copy_with(pole=...)` + zapis przez storage.
  * Wszystkie datetime są NAIWNE i oznaczają czas lokalny Europe/Warsaw.
"""

from __future__ import annotations

import hashlib
import unicodedata
import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- #
# Stałe geograficzne
# --------------------------------------------------------------------------- #

KRAKOW_CENTER: tuple[float, float] = (50.0614, 19.9366)  # Rynek Główny
# (lat_min, lon_min, lat_max, lon_max) — sanity check dla scrapera / geokodera
KRAKOW_BBOX: tuple[float, float, float, float] = (49.96, 19.78, 50.13, 20.22)


def is_in_krakow(lat: float, lon: float) -> bool:
    lat_min, lon_min, lat_max, lon_max = KRAKOW_BBOX
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


# --------------------------------------------------------------------------- #
# Helpery
# --------------------------------------------------------------------------- #


def now() -> datetime:
    """Jedyne źródło 'teraz' w aplikacji (naiwny czas lokalny)."""
    return datetime.now().replace(microsecond=0)


def new_id(prefix: str) -> str:
    """Losowe ID dla nowych obiektów, np. new_id('msg') -> 'msg_3f9a1c2b7d4e'."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def stable_id(prefix: str, *parts: str) -> str:
    """Deterministyczne ID (deduplikacja eventów ze scrapera: ten sam URL -> to samo ID)."""
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def normalize_tag(tag: str) -> str:
    """' #Jazz  Club ' -> 'jazz club'. Jedna normalizacja dla profili, eventów i filtrów."""
    return " ".join(tag.strip().lstrip("#").lower().split())


def fold_text(text: str) -> str:
    """Do wyszukiwania bez polskich znaków: 'Kraków Łódź' -> 'krakow lodz'."""
    text = text.lower().replace("ł", "l")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    seen: dict[str, None] = {}
    for raw in value:
        tag = normalize_tag(str(raw))
        if tag:
            seen.setdefault(tag, None)
    return list(seen)


# --------------------------------------------------------------------------- #
# Baza modeli
# --------------------------------------------------------------------------- #


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    def copy_with(self, **changes: Any):
        """Zwalidowana kopia ze zmianami (model_copy(update=...) NIE waliduje)."""
        return type(self).model_validate({**self.model_dump(), **changes})


# --------------------------------------------------------------------------- #
# Kategorie i słownik tagów
# --------------------------------------------------------------------------- #


class Category(str, Enum):
    MUSIC = "music"
    THEATRE = "theatre"
    CINEMA = "cinema"
    EXHIBITION = "exhibition"
    FESTIVAL = "festival"
    SPORT = "sport"
    MEETUP = "meetup"
    WORKSHOP = "workshop"
    FOOD = "food"
    OUTDOOR = "outdoor"
    OTHER = "other"


class CategoryMeta(NamedTuple):
    label: str      # etykieta PL do UI
    emoji: str
    color: str      # kolor folium.Icon (red, blue, green, purple, orange, darkred, cadetblue, ...)
    icon: str       # ikona Font Awesome dla folium.Icon(prefix="fa")


CATEGORY_META: dict[Category, CategoryMeta] = {
    Category.MUSIC: CategoryMeta("Muzyka", "🎵", "red", "music"),
    Category.THEATRE: CategoryMeta("Teatr", "🎭", "darkred", "masks-theater"),
    Category.CINEMA: CategoryMeta("Kino", "🎬", "darkblue", "film"),
    Category.EXHIBITION: CategoryMeta("Wystawy", "🖼️", "purple", "palette"),
    Category.FESTIVAL: CategoryMeta("Festiwale", "🎪", "orange", "star"),
    Category.SPORT: CategoryMeta("Sport", "🏃", "green", "person-running"),
    Category.MEETUP: CategoryMeta("Meetupy", "🤝", "cadetblue", "users"),
    Category.WORKSHOP: CategoryMeta("Warsztaty", "🛠️", "darkpurple", "screwdriver-wrench"),
    Category.FOOD: CategoryMeta("Jedzenie i picie", "🍽️", "lightred", "utensils"),
    Category.OUTDOOR: CategoryMeta("Plener", "🌳", "darkgreen", "tree"),
    Category.OTHER: CategoryMeta("Inne", "📍", "gray", "circle-info"),
}

# Kanoniczny słownik zainteresowań (podpowiedzi w profilu i filtrach; można dodawać własne).
INTEREST_TAGS: list[str] = [
    "jazz", "rock", "indie", "techno", "klasyka", "opera", "teatr", "kino", "stand-up",
    "sztuka współczesna", "fotografia", "design", "architektura", "historia", "literatura",
    "bieganie", "rower", "joga", "piłka nożna", "natura", "spacery",
    "planszówki", "gry wideo", "technologia", "python", "startupy", "nauka",
    "języki obce", "gotowanie", "street food", "kawa", "wino", "taniec", "rękodzieło",
]


# --------------------------------------------------------------------------- #
# Encje
# --------------------------------------------------------------------------- #


class Event(_Model):
    id: str
    title: str = Field(min_length=1)
    description: str = ""
    category: Category = Category.OTHER
    tags: list[str] = Field(default_factory=list)
    start: datetime
    end: datetime | None = None
    venue: str                              # nazwa miejsca, np. "Filharmonia Krakowska"
    address: str = ""
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    price_pln: float | None = None          # None = nieznana, 0 = darmowe
    url: str | None = None                  # link do źródła / biletów
    image_url: str | None = None
    source: str = "mock"                    # "mock" | "user" | "scraper:<nazwa>"
    created_by: str | None = None           # user_id, jeśli event dodany przez użytkownika

    _norm_tags = field_validator("tags", mode="before")(_normalize_tags)

    @property
    def is_free(self) -> bool:
        return self.price_pln == 0

    @property
    def end_or_start(self) -> datetime:
        return self.end or self.start

    @property
    def meta(self) -> CategoryMeta:
        return CATEGORY_META[self.category]


class User(_Model):
    id: str
    name: str = Field(min_length=1, max_length=60)
    avatar_url: str | None = None           # URL http(s) albo data URI (data:image/jpeg;base64,...)
    bio: str = ""                           # UI ogranicza do 280 znaków
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now)

    _norm_tags = field_validator("tags", mode="before")(_normalize_tags)

    @property
    def initials(self) -> str:
        parts = self.name.split()
        return "".join(p[0] for p in parts[:2]).upper() or "?"


class AttendanceStatus(str, Enum):
    GOING = "going"
    INTERESTED = "interested"


class Attendance(_Model):
    """Relacja N:M User <-> Event ('zapisałem się na wydarzenie')."""

    user_id: str
    event_id: str
    status: AttendanceStatus = AttendanceStatus.GOING
    open_to_meet: bool = True               # zgoda na pokazanie w matchingu dla innych
    created_at: datetime = Field(default_factory=now)


class MatchResult(_Model):
    """Wynik silnika matchingu (M4): 'ta osoba pasuje do Ciebie'."""

    user: User                              # dopasowana osoba (pełny obiekt -> UI nie robi lookupów)
    event_id: str | None = None             # kontekst eventu; None = dopasowanie globalne
    score: float = Field(ge=0.0, le=1.0)    # 1.0 = idealne dopasowanie
    shared_tags: list[str] = Field(default_factory=list)
    reason: str = ""                        # krótkie uzasadnienie do UI, np. "Oboje lubicie: jazz, kino"


class Recommendation(_Model):
    """Rekomendacja wydarzenia dla użytkownika (M4, opcjonalne)."""

    event: Event
    score: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class MessageKind(str, Enum):
    TEXT = "text"                           # zwykła wiadomość osoby
    SYSTEM = "system"                       # komunikat grupy, np. „Kuba dołącza do grupy”
    VOTE = "vote"                           # karta zaproszenia/głosowania (ref = GroupInvite.id)


class ChatMessage(_Model):
    id: str = Field(default_factory=lambda: new_id("msg"))
    room_id: str                            # patrz event_room_id() / dm_room_id() / group_room_id()
    user_id: str
    text: str = Field(min_length=1, max_length=1000)
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    kind: MessageKind = MessageKind.TEXT
    ref: str | None = None                  # VOTE: id zaproszenia, którego dotyczy karta


class GroupInvite(_Model):
    """Zaproszenie do grupy: najpierw głosują członkowie, potem odpowiada zaproszona osoba.

    `approvals` — członkowie „za” (zapraszający od razu). Komplet głosów -> `sent_at` (zaproszenie
    wysłane i zostaje wysłane, nawet gdy do grupy dojdzie ktoś nowy).
    """

    id: str = Field(default_factory=lambda: new_id("inv"))
    user_id: str                            # zapraszana osoba
    invited_by: str
    approvals: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now)
    sent_at: datetime | None = None

    @property
    def is_sent(self) -> bool:
        return self.sent_at is not None


class EventGroup(_Model):
    """Ekipa na wydarzenie: wspólny czat kilku osób (pokój `group_room_id(id)`).

    Jedna osoba należy najwyżej do jednej grupy na dane wydarzenie (pilnuje tego M5).
    """

    id: str = Field(default_factory=lambda: new_id("g"))
    event_id: str
    members: list[str]                      # kolejność dołączenia = kolejność awatarów nad czatem
    invites: list[GroupInvite] = Field(default_factory=list)
    created_by: str
    created_at: datetime = Field(default_factory=now)

    def invite_for(self, user_id: str) -> GroupInvite | None:
        return next((i for i in self.invites if i.user_id == user_id), None)


def event_room_id(event_id: str) -> str:
    return f"event:{event_id}"


def dm_room_id(user_a: str, user_b: str) -> str:
    """Pokój prywatny 1:1 — kolejność użytkowników nie ma znaczenia."""
    a, b = sorted((user_a, user_b))
    return f"dm:{a}:{b}"


def group_room_id(group_id: str) -> str:
    """Czat grupy na wydarzenie (EventGroup)."""
    return f"group:{group_id}"


# --------------------------------------------------------------------------- #
# Filtry
# --------------------------------------------------------------------------- #


class FilterCriteria(_Model):
    """Stan filtrów z lewego panelu. Pusta lista / None = brak ograniczenia."""

    categories: list[Category] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    tags: list[str] = Field(default_factory=list)   # event musi mieć CO NAJMNIEJ JEDEN z tagów
    query: str = ""                                  # szukanie w tytule/opisie/miejscu (bez ogonków)
    free_only: bool = False

    _norm_tags = field_validator("tags", mode="before")(_normalize_tags)

    def matches(self, event: Event) -> bool:
        if self.categories and event.category not in self.categories:
            return False
        # Przecięcie przedziałów: event trwający (np. wystawa) też pasuje do zakresu dat.
        if self.date_from and event.end_or_start.date() < self.date_from:
            return False
        if self.date_to and event.start.date() > self.date_to:
            return False
        if self.tags and not set(self.tags).intersection(event.tags):
            return False
        if self.free_only and not event.is_free:
            return False
        if self.query:
            haystack = fold_text(f"{event.title} {event.description} {event.venue} {' '.join(event.tags)}")
            if fold_text(self.query.strip()) not in haystack:
                return False
        return True


__all__ = [
    "KRAKOW_CENTER", "KRAKOW_BBOX", "is_in_krakow",
    "now", "new_id", "stable_id", "normalize_tag", "fold_text",
    "Category", "CategoryMeta", "CATEGORY_META", "INTEREST_TAGS",
    "Event", "User", "AttendanceStatus", "Attendance", "MatchResult", "Recommendation",
    "MessageKind", "ChatMessage", "GroupInvite", "EventGroup",
    "event_room_id", "dm_room_id", "group_room_id", "FilterCriteria",
]
