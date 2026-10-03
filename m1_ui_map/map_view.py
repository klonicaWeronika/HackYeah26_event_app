"""
M1 — mapa wydarzeń (folium + streamlit-folium).

Kluczowe decyzje wydajnościowe:
  * returned_objects=["last_object_clicked"] -> przesuwanie/zoom mapy NIE robi reruna aplikacji,
    rerun następuje tylko po kliknięciu pinezki.
  * Eventy w tym samym miejscu rozsuwamy po małym okręgu -> każda pinezka klikalna.
  * Klik -> event_id: najbliższa pinezka (odporne na zaokrąglenia float z JS).
"""

from __future__ import annotations

import math
from collections import defaultdict

import folium
import streamlit as st
from streamlit_folium import st_folium

from shared.formatting import format_when
from shared.models import KRAKOW_CENTER, Event

MAP_HEIGHT = 640
_SPREAD_METERS = 18.0
_CLICK_TOLERANCE_METERS = 40.0
_M_PER_DEG_LAT = 111_320.0


def pin_positions(events: list[Event]) -> dict[str, tuple[float, float]]:
    """{event_id: (lat, lon)} — współlokalizowane eventy rozsunięte po okręgu."""
    groups: dict[tuple[float, float], list[Event]] = defaultdict(list)
    for event in events:
        groups[(round(event.lat, 5), round(event.lon, 5))].append(event)

    positions: dict[str, tuple[float, float]] = {}
    for (lat, lon), group in groups.items():
        if len(group) == 1:
            positions[group[0].id] = (group[0].lat, group[0].lon)
            continue
        m_per_deg_lon = _M_PER_DEG_LAT * math.cos(math.radians(lat))
        for i, event in enumerate(sorted(group, key=lambda e: e.id)):
            angle = 2 * math.pi * i / len(group)
            positions[event.id] = (
                lat + _SPREAD_METERS * math.cos(angle) / _M_PER_DEG_LAT,
                lon + _SPREAD_METERS * math.sin(angle) / m_per_deg_lon,
            )
    return positions


def find_clicked_event(click: dict, positions: dict[str, tuple[float, float]]) -> str | None:
    """Najbliższa pinezka do punktu kliknięcia (w promieniu tolerancji)."""
    lat, lon = click.get("lat"), click.get("lng")
    if lat is None or lon is None or not positions:
        return None
    m_per_deg_lon = _M_PER_DEG_LAT * math.cos(math.radians(lat))

    def distance(pos: tuple[float, float]) -> float:
        return math.hypot((pos[0] - lat) * _M_PER_DEG_LAT, (pos[1] - lon) * m_per_deg_lon)

    event_id, pos = min(positions.items(), key=lambda item: distance(item[1]))
    return event_id if distance(pos) <= _CLICK_TOLERANCE_METERS else None


def build_map(events: list[Event], positions: dict[str, tuple[float, float]]) -> folium.Map:
    fmap = folium.Map(location=KRAKOW_CENTER, zoom_start=13, tiles="OpenStreetMap", control_scale=True)
    for event in events:
        meta = event.meta
        folium.Marker(
            location=positions[event.id],
            tooltip=f"{meta.emoji} {event.title} · {format_when(event)}",
            icon=folium.Icon(color=meta.color, icon=meta.icon, prefix="fa"),
        ).add_to(fmap)
    return fmap


def reset_map() -> None:
    """Wymusza ponowny montaż mapy (np. po zamknięciu panelu, by ten sam pin dało się kliknąć znowu)."""
    st.session_state["m1_map_nonce"] = st.session_state.get("m1_map_nonce", 0) + 1
    st.session_state.pop("m1_last_click", None)


def render_map(events: list[Event]) -> str | None:
    """Rysuje mapę. Zwraca event_id NOWO klikniętej pinezki, w innym wypadku None."""
    positions = pin_positions(events)
    output = st_folium(
        build_map(events, positions),
        key=f"m1_map_{st.session_state.get('m1_map_nonce', 0)}",
        height=MAP_HEIGHT,
        use_container_width=True,
        returned_objects=["last_object_clicked"],
    )
    click = (output or {}).get("last_object_clicked")
    # st_folium zwraca OSTATNI klik przy każdym rerunie -> reagujemy tylko na nowy.
    if not click or click == st.session_state.get("m1_last_click"):
        return None
    st.session_state["m1_last_click"] = click
    return find_clicked_event(click, positions)
