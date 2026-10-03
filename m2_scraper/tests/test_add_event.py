"""M2-09 — formularz „Dodaj wydarzenie”: logika (czyste funkcje) + UI przez AppTest na bazie w pamięci."""

from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from m2_scraper.user_events import PlaceMode, Place, build_user_event, known_places, resolve_place
from shared.models import Category, is_in_krakow
from shared.state import View
from shared.storage import Storage

NOW = datetime(2026, 10, 3, 12, 0)
TOMORROW = date(2026, 10, 4)
HEVRE = known_places()["Hevre"]
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _build(**overrides):
    fields = dict(title="Wieczór planszówek", category=Category.MEETUP, day=TOMORROW, start_time=time(19, 0),
                  duration_h=3.0, place=HEVRE, tags=["planszówki"], now=NOW)
    fields.update(overrides)
    return build_user_event("u_ola", **fields)


# --------------------------------------------------------------------------- #
# Logika
# --------------------------------------------------------------------------- #


def test_known_places_include_shared_and_extra_venues():
    places = known_places()
    assert "Filharmonia Krakowska" in places and "Teatr Groteska" in places    # KRAKOW_VENUES + venues.py
    assert all(is_in_krakow(p.lat, p.lon) for p in places.values())
    assert all(p.address.endswith("Kraków") for p in places.values() if p.address)   # np. "ul. Krakowska 13, Kraków"


def test_build_user_event_contract():
    event, errors = _build(free=True, description="Przynieś grę!", url="https://example.com")
    assert errors == []
    assert event.source == "user" and event.created_by == "u_ola" and event.id.startswith("ev_")
    assert event.start == datetime(2026, 10, 4, 19, 0) and event.end == datetime(2026, 10, 4, 22, 0)
    assert (event.venue, event.lat, event.lon) == ("Hevre", HEVRE.lat, HEVRE.lon)
    assert event.price_pln == 0 and event.tags == ["planszówki"] and event.url == "https://example.com"


def test_build_user_event_auto_tags_when_none_given():
    event, _ = _build(title="Jam session jazzowy", tags=[], description="Gramy standardy")
    assert "jazz" in event.tags


@pytest.mark.parametrize("overrides, message", [
    ({"title": "  "}, "Tytuł musi mieć"),
    ({"category": None}, "Wybierz kategorię"),
    ({"day": date(2026, 10, 2)}, "w przeszłości"),
    ({"day": None}, "datę i godzinę"),
    ({"place": None}, "Wskaż miejsce"),
    ({"url": "example.com"}, "http://"),
    ({"description": "x" * 601}, "najwyżej 600"),
    ({"duration_h": 30.0}, "Czas trwania"),
    ({"price": -5.0}, "ujemna"),
])
def test_build_user_event_validation(overrides, message):
    event, errors = _build(**overrides)
    assert event is None and any(message in e for e in errors), errors


def test_starting_now_is_not_in_the_past():
    event, errors = _build(day=NOW.date(), start_time=time(11, 50))      # 10 min temu — w tolerancji
    assert errors == [] and event is not None


def test_resolve_place_modes():
    assert resolve_place(PlaceMode.KNOWN, known_name="Hevre") == (HEVRE, None)
    assert resolve_place(PlaceMode.KNOWN, known_name=None)[1] == "Wybierz miejsce z listy."
    place, err = resolve_place(PlaceMode.MAP, venue_name="Polana", picked=(50.05, 19.93))
    assert err is None and place == Place("Polana", "", 50.05, 19.93)
    assert resolve_place(PlaceMode.MAP, picked=(52.23, 21.01))[1] == "Wskazany punkt jest poza Krakowem."
    assert resolve_place(PlaceMode.MAP)[0] is None
    place, err = resolve_place(PlaceMode.ADDRESS, venue_name="Teatr Groteska", address="ul. Skarbowa 2")
    assert err is None and place.address == "ul. Skarbowa 2, Kraków" and is_in_krakow(place.lat, place.lon)
    assert resolve_place(PlaceMode.ADDRESS, venue_name="Nieznany Lokal XYZ")[0] is None   # Nominatim off


# --------------------------------------------------------------------------- #
# UI (AppTest, izolowana baza w pamięci — nigdy data/app.db)
# --------------------------------------------------------------------------- #

FORM_SCRIPT = """
from m2_scraper.add_event_form import render_add_event_form
from shared import state
from shared.storage import get_storage

state.init()
storage = get_storage()
render_add_event_form(storage, storage.get_user(state.current_user_id()))
"""


@pytest.fixture
def memory_storage(monkeypatch, storage: Storage) -> Storage:
    monkeypatch.setattr("shared.storage._default_storage", storage)
    return storage


def _fill_and_save(at: AppTest, title: str) -> AppTest:
    at.text_input(key="m2_f_title").input(title)
    at.date_input(key="m2_f_date").set_value(date.today() + timedelta(days=1))
    at.selectbox(key="m2_f_known").select("Hevre")
    at.checkbox(key="m2_f_free").check()
    return at.button(key="m2_save").click().run()


def test_form_saves_user_event_and_opens_it_on_map(memory_storage: Storage):
    before = len(memory_storage.list_events())
    at = AppTest.from_string(FORM_SCRIPT, default_timeout=30).run()
    assert not at.exception
    at = _fill_and_save(at, "Planszówki dla nowych w mieście")
    assert not at.exception and not at.error
    added = [e for e in memory_storage.list_events() if e.source == "user"]
    assert len(memory_storage.list_events()) == before + 1 and len(added) == 1
    event = added[0]
    assert event.created_by == "u_ola" and event.venue == "Hevre" and event.price_pln == 0
    assert "planszówki" in event.tags                                 # dobrane z tytułu
    assert at.session_state["selected_event_id"] == event.id
    assert at.session_state["view"] == View.MAP
    assert at.text_input(key="m2_f_title").value == ""                # formularz wyczyszczony


def test_form_shows_errors_and_saves_nothing(memory_storage: Storage):
    before = len(memory_storage.list_events())
    at = AppTest.from_string(FORM_SCRIPT, default_timeout=30).run()
    at = at.button(key="m2_save").click().run()
    assert at.error and "Tytuł musi mieć" in at.error[0].value and "Wybierz miejsce z listy." in at.error[0].value
    assert len(memory_storage.list_events()) == before


def test_full_app_add_event_visible_on_map_and_panel(memory_storage: Storage, monkeypatch):
    """Ścieżka z aplikacji (flaga włączona tylko w teście): ⚙️ Opcje -> Dodaj -> zapis -> mapa + panel."""
    monkeypatch.setitem(__import__("shared.config", fromlist=["FEATURES"]).FEATURES, "add_event", True)
    at = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30).run()
    on_map = int(next(c.value for c in at.sidebar.caption if c.value.startswith("Na mapie")).split("**")[1])
    next(b for b in at.button if b.label == "➕ Dodaj wydarzenie").click().run()
    assert at.session_state["view"] == View.ADD_EVENT
    at = _fill_and_save(at, "Spacer fotograficzny po Kazimierzu")
    assert not at.exception
    caption = next(c.value for c in at.sidebar.caption if c.value.startswith("Na mapie"))
    assert caption == f"Na mapie: **{on_map + 1}** wydarzeń"            # od razu na mapie (ten sam przebieg)
    assert any("Spacer fotograficzny po Kazimierzu" in m.value for m in at.markdown)   # i w prawym panelu
