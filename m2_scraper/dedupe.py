"""
M2 — deduplikacja wydarzeń.

1. W obrębie źródła: to samo ID (stable_id z URL) = ten sam event (crawl stron, które przesunęły się w trakcie).
2. Między źródłami (Karnet vs Opera vs Tauron): heurystyka — ten sam dzień, zgodna godzina,
   miejsce w promieniu ~400 m i podobny tytuł (fold_text + tokeny). Wygrywa źródło o wyższym priorytecie
   (pełniejsze dane: cena, opis, współrzędne miejsca).
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable
from difflib import SequenceMatcher

from shared.models import Event, fold_text

# niższa liczba = ważniejsze źródło (bogatsze dane)
SOURCE_PRIORITY = {"scraper:karnet": 0, "scraper:opera": 1, "scraper:tauron": 2}
MAX_DISTANCE_M = 400
MAX_TIME_DIFF_MIN = 45
_STOPWORDS = {
    "w", "we", "na", "i", "z", "ze", "do", "o", "the", "a", "of", "and", "koncert", "spektakl", "pokaz",
    "opera", "krakowska", "krakow", "krakowie", "tauron", "arena", "2026", "2027", "tour",
}


def _tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", fold_text(title))
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _distance_m(a: Event, b: Event) -> float:
    lat = math.radians((a.lat + b.lat) / 2)
    dy = (a.lat - b.lat) * 111_320
    dx = (a.lon - b.lon) * 111_320 * math.cos(lat)
    return math.hypot(dx, dy)


def _has_time(e: Event) -> bool:
    return (e.start.hour, e.start.minute) != (0, 0)


def titles_similar(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    short, long_ = sorted((ta, tb), key=len)
    if short <= long_:                                   # "Faust" ⊆ "Faust Gounod Opera Krakowska"
        return True
    jaccard = len(ta & tb) / len(ta | tb)
    ratio = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return jaccard >= 0.6 or ratio >= 0.85


def is_duplicate(a: Event, b: Event) -> bool:
    if a.id == b.id:
        return True
    if a.start.date() != b.start.date():
        return False
    if _has_time(a) and _has_time(b) and abs((a.start - b.start).total_seconds()) > MAX_TIME_DIFF_MIN * 60:
        return False
    if _distance_m(a, b) > MAX_DISTANCE_M:
        return False
    return titles_similar(a.title, b.title)


def _priority(e: Event) -> tuple[int, int]:
    richness = -sum((e.price_pln is not None, bool(e.description), bool(e.tags), bool(e.image_url)))
    return SOURCE_PRIORITY.get(e.source, 9), richness


def dedupe(events: Iterable[Event], existing: Iterable[Event] = ()) -> list[Event]:
    """Zwraca eventy bez duplikatów: najpierw po ID, potem heurystycznie między źródłami.

    `existing` = eventy już w bazie z INNYCH źródeł (np. poprzednie uruchomienie `--source opera`):
    nowy event będący ich duplikatem jest pomijany (nie nadpisujemy cudzych rekordów ani zapisów na nie).
    """
    by_id: dict[str, Event] = {}
    for e in events:
        by_id[e.id] = e                                   # ten sam ID -> ostatnia (najświeższa) wersja

    kept: list[Event] = []
    buckets: dict[object, list[Event]] = defaultdict(list)
    for e in existing:
        buckets[e.start.date()].append(e)
    existing_ids = {e.id for bucket in buckets.values() for e in bucket}

    for e in sorted(by_id.values(), key=_priority):
        if e.id not in existing_ids and any(is_duplicate(e, other) for other in buckets[e.start.date()]):
            continue
        kept.append(e)
        buckets[e.start.date()].append(e)
    kept.sort(key=lambda e: (e.start, e.id))
    return kept
