"""
M2 — geokodowanie miejsc wydarzeń (nazwa/adres -> lat, lon).

Kolejność (od najszybszej):
  1. słownik znanych miejsc: shared.mock_data.KRAKOW_VENUES + m2_scraper/venues.py (offline),
  2. cache na dysku data/cache/geocode.json — także wyniki puste (drugi raz nie pytamy),
  3. Nominatim (OpenStreetMap) przez PoliteHttp: ≥ 1,1 s między zapytaniami, identyfikujący User-Agent,
     countrycodes=pl, viewbox=KRAKOW_BBOX, bounded=1; wynik sprawdzany przez is_in_krakow.
     Zapytanie idzie TYLKO, gdy robots.txt na to pozwala. Stan na 2026-10-03: `Disallow: /search`
     -> Nominatim jest pomijany (decyzja i alternatywy: m2_scraper/README.md).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from m2_scraper.base import PoliteHttp
from m2_scraper.venues import EXTRA_VENUES
from shared.mock_data import KRAKOW_VENUES
from shared.models import KRAKOW_BBOX, fold_text, is_in_krakow
from shared.storage import PROJECT_ROOT

log = logging.getLogger(__name__)

GEOCODE_CACHE = PROJECT_ROOT / "data" / "cache" / "geocode.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_DELAY_S = 1.1                  # polityka Nominatim: maks. 1 zapytanie/s

Coords = tuple[float, float]


def _known_places() -> dict[str, Coords]:
    places = {fold_text(v.name): (v.lat, v.lon) for v in KRAKOW_VENUES.values()}
    for venue in EXTRA_VENUES:
        places.setdefault(fold_text(venue.name), (venue.lat, venue.lon))
    return places


_KNOWN = _known_places()


def known_venue(venue: str) -> Coords | None:
    """Słownik: dokładnie po nazwie (bez ogonków/wielkości liter), potem dopasowanie częściowe."""
    key = fold_text(venue or "").strip()
    if len(key) < 3:
        return None
    if key in _KNOWN:
        return _KNOWN[key]
    for name, coords in _KNOWN.items():   # "Kino Kijów Centrum" -> "kino kijow"
        if (len(name) >= 5 and name in key) or (len(key) >= 6 and key in name):
            return coords
    return None


def nominatim_url(query: str) -> str:
    lat_min, lon_min, lat_max, lon_max = KRAKOW_BBOX
    params: dict[str, Any] = {
        "q": query, "format": "jsonv2", "limit": 1, "countrycodes": "pl",
        "viewbox": f"{lon_min},{lat_max},{lon_max},{lat_min}", "bounded": 1,
    }
    return f"{NOMINATIM_URL}?{urlencode(params)}"


def _queries(venue: str, address: str) -> list[str]:
    street = (address or "").replace(", Kraków", "").strip()
    return [q for q in (f"{street}, Kraków" if street else "", f"{venue}, Kraków" if venue else "") if q]


class Geocoder:
    """Słownik -> cache -> Nominatim. `http` wstrzykiwalne (testy offline z udawanym klientem)."""

    def __init__(self, cache_path: Path = GEOCODE_CACHE, *, http: PoliteHttp | None = None):
        self.cache_path = Path(cache_path)
        self._http = http
        self._cache: dict[str, list[float] | None] | None = None
        self._lock = threading.Lock()
        self._nominatim_ok: bool | None = None

    @property
    def http(self) -> PoliteHttp:
        if self._http is None:
            self._http = PoliteHttp(delay_s=NOMINATIM_DELAY_S)
        return self._http

    def _load(self) -> dict[str, list[float] | None]:
        if self._cache is None:
            self._cache = {}
            if self.cache_path.exists():
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        return self._cache

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._load(), ensure_ascii=False, indent=1), encoding="utf-8")

    def nominatim_allowed(self) -> bool:
        """robots.txt Nominatim (sprawdzane raz na proces; błąd sieci = nie pytamy)."""
        if self._nominatim_ok is None:
            try:
                self._nominatim_ok = self.http.allowed(nominatim_url("Kraków"))
            except Exception:  # noqa: BLE001
                self._nominatim_ok = False
            if not self._nominatim_ok:
                log.info("Nominatim pominięty: robots.txt nie pozwala na /search (albo brak sieci)")
        return self._nominatim_ok

    def _nominatim(self, query: str) -> Coords | None:
        for item in json.loads(self.http.get_text(nominatim_url(query))) or []:
            lat, lon = float(item["lat"]), float(item["lon"])
            if is_in_krakow(lat, lon):
                return lat, lon
        return None

    def geocode(self, venue: str, address: str = "") -> Coords | None:
        if not (venue or "").strip() and not (address or "").strip():
            return None
        known = known_venue(venue)
        if known:
            return known

        key = fold_text(f"{venue}|{address}").strip()
        with self._lock:
            cache = self._load()
            if key in cache:
                hit = cache[key]
                return (hit[0], hit[1]) if hit and is_in_krakow(*hit) else None
            if not self.nominatim_allowed():
                return None                     # bez zapisu: gdy robots się zmieni, spróbujemy ponownie
            coords: Coords | None = None
            for query in _queries(venue, address):
                try:
                    coords = self._nominatim(query)
                except Exception as exc:  # noqa: BLE001 — błąd sieci != "nie ma takiego miejsca"
                    log.warning("Nominatim: błąd dla %r: %s", query, exc)
                    return None
                if coords:
                    break
            cache[key] = list(coords) if coords else None
            self._save()
            return coords


_default: Geocoder | None = None


def default_geocoder() -> Geocoder:
    global _default
    if _default is None:
        _default = Geocoder()
    return _default


def geocode(venue: str, address: str = "") -> Coords | None:
    """Zwraca (lat, lon) w granicach Krakowa albo None (event bez współrzędnych nie trafia na mapę)."""
    return default_geocoder().geocode(venue, address)
