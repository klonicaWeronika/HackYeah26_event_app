"""M1 — testy mapy (bez przeglądarki) + smoke test całej aplikacji przez streamlit AppTest."""

import math
from datetime import datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from m1_ui_map.location import Place
from m1_ui_map.map_view import build_map, find_clicked_event, pin_positions, pins_payload
from shared.models import Event
from shared.storage import Storage


def test_colocated_events_get_distinct_pins(storage: Storage):
    events = storage.list_events()
    positions = pin_positions(events)
    assert len(positions) == len(events)
    assert len(set(positions.values())) == len(events), "każda pinezka musi mieć unikalną pozycję"


def test_click_maps_back_to_event(storage: Storage):
    positions = pin_positions(storage.list_events())
    for event_id, (lat, lon) in positions.items():
        assert find_clicked_event({"lat": lat, "lng": lon}, positions) == event_id
    assert find_clicked_event({"lat": 50.0, "lng": 19.0}, positions) is None   # klik obok pinezek


def test_pins_payload_has_every_event_and_one_selected(storage: Storage):
    events = storage.list_events()
    positions = pin_positions(events)
    pins = pins_payload(events, positions, selected_id=events[0].id)
    assert [p[0] for p in pins] == [e.id for e in events]
    assert sum(p[6] for p in pins) == 1 and pins[0][6] == 1
    assert all(p[3].startswith("#") and p[4] for p in pins)                    # kolor kategorii + ikona FA
    assert find_clicked_event({"lat": pins[1][1], "lng": pins[1][2]}, positions) == pins[1][0]


def test_build_map_contains_layers_and_radius(storage: Storage):
    events = storage.list_events()
    html = build_map(events, pin_positions(events), radius_center=Place(50.06, 19.94), radius_km=2.0)
    rendered = html.get_root().render()
    assert "markerClusterGroup" in rendered and "L.circle(" in rendered
    assert "[50.06, 19.94, 2000.0]" in rendered
    for event in events:
        assert f'"{event.id}"' in rendered


def test_tooltip_escapes_event_data():
    evil = Event(id="x", title="<img src=x onerror=alert(1)>", start=datetime(2026, 1, 1), venue="v",
                 lat=50.05, lon=19.94)
    pins = pins_payload([evil], pin_positions([evil]))
    assert "<img" not in pins[0][5] and "&lt;img" in pins[0][5]


def test_pin_spread_is_small():
    same = [Event(id=f"e{i}", title="t", start=datetime(2026, 1, 1), venue="v", lat=50.05, lon=19.94)
            for i in range(3)]
    for lat, lon in pin_positions(same).values():
        meters = math.hypot((lat - 50.05) * 111_320, (lon - 19.94) * 111_320 * math.cos(math.radians(50.05)))
        assert 10 < meters < 30


def test_app_smoke(tmp_path, monkeypatch):
    """Cała aplikacja renderuje się bez wyjątku na mockach (izolowana baza, nie data/app.db)."""
    monkeypatch.setattr("shared.storage._default_storage", Storage(tmp_path / "smoke.db"))
    at = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "app.py"), default_timeout=30).run()
    assert not at.exception, at.exception
    assert at.session_state["view"] == "map"
