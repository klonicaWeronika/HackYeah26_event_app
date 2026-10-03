"""
M1 — lokalizacja i promień: „pokaż wydarzenia w promieniu X km od miejsca Y”.

Czysta logika (bez Streamlita) — filtr promienia działa w M1 na liście z `Storage.list_events`, więc
kontrakt `FilterCriteria` w `shared/` zostaje bez zmian.
"""

from __future__ import annotations

import math
from typing import NamedTuple

from shared.models import Event

PICKED_PLACE = "Wybrany punkt"      # środek wskazany kliknięciem na mapie
RADIUS_STEPS_KM: tuple[float, ...] = (0.5, 1.0, 2.0, 3.0, 5.0, 10.0)
DEFAULT_RADIUS_KM = 2.0
_EARTH_RADIUS_KM = 6371.0088


class Place(NamedTuple):
    lat: float
    lon: float


# Popularne punkty startowe w Krakowie (środek promienia bez geokodowania i bez sieci).
PLACES: dict[str, Place] = {
    "Rynek Główny": Place(50.0614, 19.9366),
    "Kazimierz": Place(50.0515, 19.9455),
    "Podgórze": Place(50.0441, 19.9547),
    "Zabłocie": Place(50.0478, 19.9618),
    "Stare Miasto — Wawel": Place(50.0541, 19.9354),
    "Krowodrza": Place(50.0742, 19.9150),
    "Dębniki": Place(50.0462, 19.9210),
    "Ruczaj": Place(50.0236, 19.9093),
    "Bronowice": Place(50.0811, 19.8920),
    "Prądnik Biały": Place(50.0920, 19.9300),
    "Czyżyny": Place(50.0725, 20.0085),
    "Nowa Huta": Place(50.0718, 20.0377),
}


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Odległość po kuli (haversine) w km."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = phi2 - phi1, math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def event_distance_km(event: Event, center: Place) -> float:
    return distance_km(center.lat, center.lon, event.lat, event.lon)


def within_radius(events: list[Event], center: Place | None, radius_km: float | None) -> list[Event]:
    """Eventy w promieniu (włącznie z brzegiem). Brak środka lub promienia = bez ograniczenia."""
    if center is None or not radius_km:
        return events
    return [e for e in events if event_distance_km(e, center) <= radius_km]


def format_distance(km: float) -> str:
    """'350 m', '1,2 km', '12 km' — polski przecinek dziesiętny."""
    if km < 1:
        return f"{max(round(km * 1000, -1), 10):.0f} m"
    if km < 10:
        return f"{km:.1f} km".replace(".", ",")
    return f"{km:.0f} km"


def format_radius(km: float) -> str:
    return f"{km:g} km".replace(".", ",")


def zoom_for_radius(radius_km: float) -> int:
    """Zoom mapy, przy którym cały okrąg mieści się w widoku między panelami."""
    for limit, zoom in ((0.6, 16), (1.2, 15), (2.5, 14), (5.5, 13), (11.0, 12)):
        if radius_km <= limit:
            return zoom
    return 11
