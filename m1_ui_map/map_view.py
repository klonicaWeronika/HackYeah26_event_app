"""
M1 — pełnoekranowa mapa wydarzeń (folium + streamlit-folium).

Kluczowe decyzje:
  * Mapa bazowa (kafelki + stały CSS/JS w iframe) się nie zmienia -> komponent nigdy się nie przemontowuje,
    zoom i widok zostają. Pinezki, wyróżnienie i okrąg promienia idą przez `feature_group_to_add`:
    streamlit-folium podmienia je w locie, bez resetu widoku.
  * Wszystkie pinezki to JEDEN element JS z danymi w JSON (zamiast setek obiektów folium) -> szybki rerun.
  * returned_objects bez bounds/zoom -> przesuwanie i zoom NIE robią reruna; rerun tylko po kliknięciu.
  * Kliknięcie pinezki rozpoznajemy po liczniku kliknięć (ten sam pin da się kliknąć drugi raz) i po
    dokładnej pozycji (klik w klaster ma pozycję średnią, więc nie wybiera przypadkowego eventu).
  * Eventy w tym samym miejscu rozsuwamy po małym okręgu -> każda pinezka klikalna.
"""

from __future__ import annotations

import html
import json
import math
from collections import defaultdict
from typing import NamedTuple

import folium
import streamlit as st
from branca.element import Element, MacroElement
from folium.elements import JSCSSMixin
from jinja2 import Template
from streamlit_folium import st_folium

from m1_ui_map.location import Place
from shared.formatting import format_when
from shared.models import KRAKOW_CENTER, Category, Event

MAP_FRAME_HEIGHT = 720          # nominalna wysokość komponentu; CSS rozciąga mapę na cały ekran
BRAND_COLOR = "#E4572E"
_SPREAD_METERS = 18.0
_CLICK_TOLERANCE_METERS = 2.0   # klik w pinezkę zwraca jej dokładną pozycję
_M_PER_DEG_LAT = 111_320.0
_RETURNED = ["last_object_clicked", "last_object_clicked_count", "last_clicked"]
_CLUSTER_CDN = "https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3"

# Kolory kategorii (pinezki na mapie, kółka na pasku kategorii, miniatury na liście).
CATEGORY_COLORS: dict[Category, str] = {
    Category.MUSIC: "#F43F5E",
    Category.THEATRE: "#8B5CF6",
    Category.CINEMA: "#3B82F6",
    Category.EXHIBITION: "#EC4899",
    Category.FESTIVAL: "#F59E0B",
    Category.SPORT: "#22C55E",
    Category.MEETUP: "#06B6D4",
    Category.WORKSHOP: "#F97316",
    Category.FOOD: "#EF4444",
    Category.OUTDOOR: "#10B981",
    Category.OTHER: "#64748B",
}

# OpenStreetMap (bez klucza API). Nowocześniejszy wygląd daje filtr CSS na warstwie kafelków:
# stonowane kolory w jasnym motywie, odwrócone (ciemna mapa) w ciemnym.
_TILES_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_TILES_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
_TILE_FILTER = {
    False: "saturate(0.55) brightness(1.05) contrast(0.92)",
    True: "invert(1) hue-rotate(180deg) brightness(0.92) contrast(0.88) saturate(0.45)",
}
_MAP_BG = {False: "#EEF0F2", True: "#15171C"}


class MapClick(NamedTuple):
    event_id: str | None = None                 # NOWO kliknięta pinezka
    point: tuple[float, float] | None = None    # NOWY klik w puste miejsce mapy (lat, lon)


class MapFocus(NamedTuple):
    """Dokąd przesunąć widok (tylko po akcji spoza mapy: wybór z listy, zmiana promienia)."""

    lat: float
    lon: float
    zoom: int | None = None


# --------------------------------------------------------------------------- #
# Geometria pinezek
# --------------------------------------------------------------------------- #

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
    """Pinezka w miejscu kliknięcia (tolerancja na zaokrąglenia float z JS)."""
    lat, lon = click.get("lat"), click.get("lng")
    if lat is None or lon is None or not positions:
        return None
    m_per_deg_lon = _M_PER_DEG_LAT * math.cos(math.radians(lat))

    def distance(pos: tuple[float, float]) -> float:
        return math.hypot((pos[0] - lat) * _M_PER_DEG_LAT, (pos[1] - lon) * m_per_deg_lon)

    event_id, pos = min(positions.items(), key=lambda item: distance(item[1]))
    return event_id if distance(pos) <= _CLICK_TOLERANCE_METERS else None


# --------------------------------------------------------------------------- #
# Mapa bazowa: kafelki + stały wygląd wewnątrz iframe
# --------------------------------------------------------------------------- #

_FRAME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body {margin: 0; padding: 0; overflow: hidden; background: __BG__;}
.leaflet-tile-pane {filter: __TILE_FILTER__;}
#parent, .float-child {width: 100vw;}
#map_div {width: 100vw !important; height: 100vh !important;}
.leaflet-container {font-family: Inter, system-ui, -apple-system, "Segoe UI", sans-serif; background: __BG__;}

/* Sterowanie na dole, na środku — panele po bokach go nie zasłaniają. */
.leaflet-bottom.leaflet-left {
  left: 50%; transform: translateX(-50%); display: flex; flex-direction: column; align-items: center;
  gap: 6px; padding-bottom: 10px;
}
.leaflet-bottom.leaflet-left .leaflet-control {margin: 0; float: none;}
.leaflet-control-zoom {order: 1;}
.leaflet-control-scale {order: 2;}
.leaflet-control-attribution {order: 3;}
.leaflet-bar.leaflet-control-zoom {
  display: flex; border: none; border-radius: 999px; overflow: hidden;
  box-shadow: 0 6px 20px -6px rgba(15, 23, 42, .35), 0 0 0 1px __LINE__;
}
.leaflet-bar.leaflet-control-zoom a {
  width: 42px; height: 38px; line-height: 38px; border: none; border-radius: 0 !important;
  background: __SURFACE__; color: __TEXT__; font: 600 18px/38px Inter, sans-serif;
}
.leaflet-bar.leaflet-control-zoom a + a {border-left: 1px solid __LINE__;}
.leaflet-bar.leaflet-control-zoom a:hover {background: __HOVER__;}
.leaflet-bar.leaflet-control-zoom a.krk-home {font-size: 15px;}
.leaflet-control-scale-line {
  background: __SURFACE__; color: __MUTED__; border-color: __MUTED__; font-size: 10px; border-radius: 3px;
}
.leaflet-control-attribution {
  background: __SURFACE__ !important; color: __MUTED__; border-radius: 6px; font-size: 10px; padding: 1px 8px;
}
.leaflet-control-attribution a {color: __MUTED__;}

/* Pinezki: okrągłe znaczki kategorii. */
.krk-pin-wrap {background: none; border: none;}
.krk-pin {
  --c: #E4572E; box-sizing: border-box; width: 100%; height: 100%; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; color: #fff; font-size: 13px;
  background: linear-gradient(140deg, color-mix(in srgb, var(--c) 62%, #fff), var(--c));
  box-shadow: 0 0 0 2.5px __PIN_RING__, 0 4px 10px rgba(15, 23, 42, .35);
  transition: transform .15s ease;
}
.krk-pin:hover {transform: scale(1.18);}
.krk-pin.is-selected {
  font-size: 18px;
  box-shadow: 0 0 0 3px __PIN_RING__, 0 0 0 8px color-mix(in srgb, var(--c) 35%, transparent),
              0 10px 22px rgba(15, 23, 42, .4);
  animation: krk-pulse 1.8s ease-out infinite;
}
@keyframes krk-pulse {
  0% {box-shadow: 0 0 0 3px __PIN_RING__, 0 0 0 0 color-mix(in srgb, var(--c) 55%, transparent),
       0 10px 22px rgba(15, 23, 42, .4);}
  70% {box-shadow: 0 0 0 3px __PIN_RING__, 0 0 0 16px color-mix(in srgb, var(--c) 0%, transparent),
       0 10px 22px rgba(15, 23, 42, .4);}
  100% {box-shadow: 0 0 0 3px __PIN_RING__, 0 0 0 0 transparent, 0 10px 22px rgba(15, 23, 42, .4);}
}

/* Klastry. */
.krk-cluster-wrap {background: none; border: none;}
.krk-cluster {
  width: 100%; height: 100%; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  background: rgba(228, 87, 46, .22);
}
.krk-cluster span {
  width: calc(100% - 10px); height: calc(100% - 10px); border-radius: 50%; display: flex;
  align-items: center; justify-content: center; color: #fff; font: 700 13px Inter, sans-serif;
  background: linear-gradient(140deg, #F2784B, #D9431A);
  box-shadow: 0 0 0 2px __PIN_RING__, 0 4px 12px rgba(217, 67, 26, .45);
}

/* Okrąg promienia: środek. */
.krk-center {
  width: 100%; height: 100%; border-radius: 50%; background: #E4572E; box-sizing: border-box;
  border: 3px solid #fff; box-shadow: 0 0 0 6px rgba(228, 87, 46, .25), 0 2px 8px rgba(0, 0, 0, .3);
}

/* Dymki po najechaniu. */
.leaflet-tooltip.krk-tip {
  background: __SURFACE__; color: __TEXT__; border: none; border-radius: 12px; padding: 8px 12px;
  box-shadow: 0 10px 28px -8px rgba(15, 23, 42, .45), 0 0 0 1px __LINE__;
  width: max-content; max-width: 250px;
  white-space: normal; font: 500 12px/1.35 Inter, sans-serif;
}
.leaflet-tooltip-top.krk-tip::before {border-top-color: __SURFACE__;}
.krk-tip b {display: block; font-size: 13px; font-weight: 650; margin-bottom: 2px;}
.krk-tip small {color: __MUTED__; font-size: 11.5px;}
</style>
"""

_FRAME_TOKENS = {
    False: {"__SURFACE__": "#FFFFFF", "__TEXT__": "#0F172A", "__MUTED__": "#64748B",
            "__LINE__": "rgba(15, 23, 42, .08)", "__HOVER__": "#F1F5F9", "__PIN_RING__": "#FFFFFF"},
    True: {"__SURFACE__": "#1A1D26", "__TEXT__": "#F1F5F9", "__MUTED__": "#94A3B8",
           "__LINE__": "rgba(255, 255, 255, .10)", "__HOVER__": "#262A35", "__PIN_RING__": "#1A1D26"},
}


class _MapChrome(MacroElement):
    """Stały JS mapy bazowej: atrybucja na dół-środek + przycisk „wyśrodkuj na Krakowie” obok zoomu."""

    _template = Template("""
        {% macro script(this, kwargs) %}
        (function (map) {
            map.attributionControl.setPosition('bottomleft');
            map.attributionControl.setPrefix(false);
            var zoom = document.querySelector('.leaflet-control-zoom');
            if (zoom && !zoom.querySelector('.krk-home')) {
                var home = L.DomUtil.create('a', 'krk-home', zoom);
                home.href = '#'; home.title = 'Wyśrodkuj na Krakowie'; home.setAttribute('role', 'button');
                home.innerHTML = '<i class="fa-solid fa-location-crosshairs"></i>';
                L.DomEvent.on(home, 'click', function (e) {
                    L.DomEvent.preventDefault(e);
                    map.flyTo({{ this.center }}, 13, {duration: 0.6});
                });
            }
        })({{ this._parent.get_name() }});
        {% endmacro %}
    """)

    def __init__(self) -> None:
        super().__init__()
        self._name = "MapChrome"
        self.center = json.dumps(list(KRAKOW_CENTER))


def build_base_map(dark: bool = False) -> folium.Map:
    fmap = folium.Map(
        location=KRAKOW_CENTER, zoom_start=13, tiles=None, control_scale=True, zoom_control="bottomleft",
        min_zoom=11, max_zoom=19,
    )
    folium.TileLayer(_TILES_URL, attr=_TILES_ATTR, name="OpenStreetMap", max_zoom=19).add_to(fmap)
    css = _FRAME_CSS.replace("__BG__", _MAP_BG[dark]).replace("__TILE_FILTER__", _TILE_FILTER[dark])
    for token, value in _FRAME_TOKENS[dark].items():
        css = css.replace(token, value)
    fmap.get_root().header.add_child(Element(css), name="krk_css")
    fmap.add_child(_MapChrome())
    return fmap


# --------------------------------------------------------------------------- #
# Warstwy dynamiczne: pinezki + klastry + wyróżnienie + okrąg promienia
# --------------------------------------------------------------------------- #

def _tooltip_html(event: Event) -> str:
    return (
        f"<b>{html.escape(event.title)}</b>"
        f"<small>{html.escape(format_when(event))} · {html.escape(event.venue)}</small>"
    )


def pins_payload(
    events: list[Event], positions: dict[str, tuple[float, float]], selected_id: str | None = None,
) -> list[list]:
    """Dane pinezek dla JS: [id, lat, lon, kolor, ikona FA, tooltip HTML, wybrany(0/1)]."""
    return [
        [
            event.id, round(positions[event.id][0], 6), round(positions[event.id][1], 6),
            CATEGORY_COLORS[event.category], event.meta.icon, _tooltip_html(event),
            int(event.id == selected_id),
        ]
        for event in events
    ]


class MapLayers(JSCSSMixin, MacroElement):
    """Jeden element JS: klaster pinezek, wybrana pinezka nad klastrem, okrąg promienia ze środkiem."""

    _template = Template("""
        {% macro script(this, kwargs) %}
        (function (group) {
            function pinIcon(d, selected) {
                var size = selected ? 42 : 30;
                return L.divIcon({
                    className: 'krk-pin-wrap', iconSize: [size, size], iconAnchor: [size / 2, size / 2],
                    html: '<div class="krk-pin' + (selected ? ' is-selected' : '')
                        + '" style="--c:' + d[3] + '">'
                        + '<i class="fa-solid fa-' + d[4] + '"></i></div>'
                });
            }
            // Wyróżnienie od razu po kliknięciu (serwer potwierdzi je przy następnym przebiegu).
            var current = null;
            function highlight(m) {
                if (current && current !== m) {
                    current.setIcon(pinIcon(current.krk, false));
                    current.setZIndexOffset(0);
                }
                m.setIcon(pinIcon(m.krk, true));
                m.setZIndexOffset(1000);
                current = m;
            }
            function tooltip(m, d) {
                m.krk = d;
                m.bindTooltip(d[5], {direction: 'top', offset: [0, -14], className: 'krk-tip', opacity: 1});
                m.on('click', function () { highlight(m); });
            }
            var radius = {{ this.radius }};
            if (radius) {
                L.circle([radius[0], radius[1]], {
                    radius: radius[2], color: '{{ this.color }}', weight: 2, dashArray: '6 8',
                    fillColor: '{{ this.color }}', fillOpacity: 0.07, interactive: false
                }).addTo(group);
                L.marker([radius[0], radius[1]], {
                    interactive: false, keyboard: false,
                    icon: L.divIcon({className: 'krk-pin-wrap', html: '<div class="krk-center"></div>',
                                     iconSize: [18, 18], iconAnchor: [9, 9]})
                }).addTo(group);
            }
            var cluster = L.markerClusterGroup({
                maxClusterRadius: 46, showCoverageOnHover: false, spiderfyOnMaxZoom: true,
                iconCreateFunction: function (c) {
                    var n = c.getChildCount(), s = n < 10 ? 38 : n < 50 ? 44 : n < 200 ? 52 : 60;
                    return L.divIcon({html: '<div class="krk-cluster"><span>' + n + '</span></div>',
                                      className: 'krk-cluster-wrap', iconSize: [s, s]});
                }
            });
            var pins = {{ this.pins }};
            pins.forEach(function (d) {
                if (d[6]) {
                    var sel = L.marker([d[1], d[2]],
                                       {icon: pinIcon(d, true), zIndexOffset: 1000, riseOnHover: true});
                    tooltip(sel, d);
                    sel.addTo(group);
                    current = sel;
                    return;
                }
                var m = L.marker([d[1], d[2]], {icon: pinIcon(d, false), riseOnHover: true});
                tooltip(m, d);
                cluster.addLayer(m);
            });
            cluster.addTo(group);
        })({{ this._parent.get_name() }});
        {% endmacro %}
    """)

    default_js = [("markerclusterjs", f"{_CLUSTER_CDN}/leaflet.markercluster.js")]
    default_css = [("markerclustercss", f"{_CLUSTER_CDN}/MarkerCluster.css")]

    def __init__(self, pins: list[list], radius: tuple[float, float, float] | None) -> None:
        super().__init__()
        self._name = "MapLayers"
        self.pins = json.dumps(pins)
        self.radius = json.dumps(list(radius) if radius else None)
        self.color = BRAND_COLOR


def build_layers(
    events: list[Event],
    positions: dict[str, tuple[float, float]],
    *,
    selected_id: str | None = None,
    radius_center: Place | None = None,
    radius_km: float | None = None,
) -> folium.FeatureGroup:
    radius = (radius_center.lat, radius_center.lon, radius_km * 1000) if radius_center and radius_km else None
    group = folium.FeatureGroup(name="Wydarzenia")
    group.add_child(MapLayers(pins_payload(events, positions, selected_id), radius))
    return group


def build_map(
    events: list[Event], positions: dict[str, tuple[float, float]], *, dark: bool = False, **layer_options,
) -> folium.Map:
    """Mapa z wszystkimi warstwami w jednym obiekcie (testy, podgląd poza Streamlitem)."""
    fmap = build_base_map(dark)
    build_layers(events, positions, **layer_options).add_to(fmap)
    return fmap


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #

def reset_map() -> None:
    """Wymusza ponowny montaż mapy (widok wraca do Krakowa). Zwykle niepotrzebne — mapa trzyma stan sama."""
    st.session_state["m1_map_nonce"] = st.session_state.get("m1_map_nonce", 0) + 1
    st.session_state.pop("m1_last_click", None)
    st.session_state.pop("m1_last_point", None)


def render_map(
    events: list[Event],
    *,
    selected_id: str | None = None,
    radius_center: Place | None = None,
    radius_km: float | None = None,
    focus: MapFocus | None = None,
    dark: bool = False,
) -> MapClick:
    """Rysuje mapę na cały ekran. Zwraca NOWE kliknięcie (pinezka albo puste miejsce mapy)."""
    positions = pin_positions(events)
    output = st_folium(
        build_base_map(dark),
        key=f"m1_map_{st.session_state.get('m1_map_nonce', 0)}",
        height=MAP_FRAME_HEIGHT,
        use_container_width=True,
        returned_objects=_RETURNED,
        feature_group_to_add=build_layers(
            events, positions, selected_id=selected_id, radius_center=radius_center, radius_km=radius_km,
        ),
        center=(focus.lat, focus.lon) if focus else None,
        zoom=focus.zoom if focus else None,
    ) or {}

    # st_folium zwraca OSTATNI stan przy każdym rerunie -> reagujemy tylko na zmiany.
    event_id = point = None
    marker = (output.get("last_object_clicked_count"), output.get("last_object_clicked"))
    if marker[1] and marker != st.session_state.get("m1_last_click"):
        st.session_state["m1_last_click"] = marker
        event_id = find_clicked_event(marker[1], positions)
    clicked = output.get("last_clicked")
    if clicked and clicked != st.session_state.get("m1_last_point"):
        st.session_state["m1_last_point"] = clicked
        point = (clicked["lat"], clicked["lng"])
    return MapClick(event_id, point)
