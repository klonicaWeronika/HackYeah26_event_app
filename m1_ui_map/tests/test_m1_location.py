"""M1 — lokalizacja i promień (czysta logika, bez Streamlita)."""

from datetime import datetime

import pytest

from m1_ui_map.location import (
    PLACES, distance_km, format_distance, format_radius, within_radius, zoom_for_radius,
)
from shared.models import Event


def _event(eid: str, lat: float, lon: float) -> Event:
    return Event(id=eid, title=eid, start=datetime(2026, 10, 3, 20), venue="v", lat=lat, lon=lon)


def test_distance_rynek_to_kazimierz_is_about_1_3_km():
    rynek, kazimierz = PLACES["Rynek Główny"], PLACES["Kazimierz"]
    assert distance_km(rynek.lat, rynek.lon, kazimierz.lat, kazimierz.lon) == pytest.approx(1.30, abs=0.1)
    assert distance_km(rynek.lat, rynek.lon, rynek.lat, rynek.lon) == 0


def test_within_radius_includes_edge_and_skips_far_events():
    center = PLACES["Rynek Główny"]
    near = _event("near", center.lat + 0.004, center.lon)            # ~0,45 km
    far = _event("far", PLACES["Nowa Huta"].lat, PLACES["Nowa Huta"].lon)
    assert [e.id for e in within_radius([near, far], center, 1.0)] == ["near"]
    assert within_radius([near, far], None, 1.0) == [near, far]       # cały Kraków
    assert within_radius([near, far], center, None) == [near, far]


@pytest.mark.parametrize("km, text", [(0.004, "10 m"), (0.347, "350 m"), (1.24, "1,2 km"), (12.4, "12 km")])
def test_format_distance(km, text):
    assert format_distance(km) == text


def test_format_radius_and_zoom():
    assert format_radius(0.5) == "0,5 km" and format_radius(2.0) == "2 km"
    zooms = [zoom_for_radius(r) for r in (0.5, 1, 2, 3, 5, 10, 20)]
    assert zooms == sorted(zooms, reverse=True) and zooms[0] == 16
