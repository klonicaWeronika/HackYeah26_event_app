"""
M2 — geokodowanie miejsc wydarzeń (nazwa/adres -> lat, lon).

Kolejność (od najszybszej):
  1. słownik znanych miejsc Krakowa (shared.mock_data.KRAKOW_VENUES),
  2. cache na dysku data/cache/geocode.json,
  3. TODO(M2): Nominatim (OpenStreetMap) — max 1 zapytanie/s, własny User-Agent,
     wynik zawsze zapisywany do cache.
"""

from __future__ import annotations

import json

from shared.mock_data import KRAKOW_VENUES
from shared.models import fold_text, is_in_krakow
from shared.storage import PROJECT_ROOT

GEOCODE_CACHE = PROJECT_ROOT / "data" / "cache" / "geocode.json"

_KNOWN = {fold_text(v.name): (v.lat, v.lon) for v in KRAKOW_VENUES.values()}


def _load_cache() -> dict[str, list[float]]:
    if GEOCODE_CACHE.exists():
        return json.loads(GEOCODE_CACHE.read_text(encoding="utf-8"))
    return {}


def geocode(venue: str, address: str = "") -> tuple[float, float] | None:
    """Zwraca (lat, lon) w granicach Krakowa albo None (event bez współrzędnych nie trafia na mapę)."""
    key = fold_text(venue).strip()
    if not key:
        return None
    if key in _KNOWN:
        return _KNOWN[key]
    for known_name, coords in _KNOWN.items():   # dopasowanie częściowe: "Kino Kijów Centrum" -> "kino kijow"
        if known_name in key or key in known_name:
            return coords

    cached = _load_cache().get(fold_text(f"{venue}|{address}"))
    if cached and is_in_krakow(*cached):
        return cached[0], cached[1]

    # TODO(M2): zapytanie do Nominatim + zapis do GEOCODE_CACHE
    return None
