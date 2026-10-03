"""M1 — górny pasek, menu, filtry, lista i panele: logika etykiet + zachowanie w całej aplikacji (AppTest)."""

import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from m1_ui_map.layout import (
    LOGO_MARK_PATH, LOGO_PATH, category_label, date_range_for, event_card_html, full_date, plans_caption,
    sort_events,
)
from m1_ui_map.location import PLACES, Place
from shared.models import CATEGORY_META, Category, Event, FilterCriteria
from shared.state import View
from shared.storage import Storage

APP_PATH = str(Path(__file__).resolve().parents[2] / "app.py")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


@pytest.fixture
def app_storage(tmp_path, monkeypatch) -> Storage:
    store = Storage(tmp_path / "layout.db")
    monkeypatch.setattr("shared.storage._default_storage", store)
    yield store
    store.close()


def _run_app(user_id: str = "u_ola") -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.query_params["user"] = user_id
    return at.run()


def _results_count(at: AppTest) -> int:
    header = next(m.value for m in at.markdown if 'class="m1-count"' in m.value)
    return int(re.search(r'class="m1-count">(\d+)<', header).group(1))


def _event(**fields) -> Event:
    base = dict(id="e1", title="Koncert", start=datetime(2026, 10, 3, 20), venue="Alchemia",
                lat=50.05, lon=19.94)
    return Event(**{**base, **fields})


def test_category_labels_use_material_icons_not_emoji():
    for category in Category:
        label = category_label(category)
        assert re.fullmatch(r":material/[a-z_]+: .+", label), label
        assert CATEGORY_META[category].label in label
        assert not _EMOJI.search(label)


@pytest.mark.parametrize("going, expected", [
    (0, "Brak planów — wybierz coś na mapie"),
    (1, "1 wydarzenie w planach"),
    (3, "3 wydarzenia w planach"),
    (5, "5 wydarzeń w planach"),
    (12, "12 wydarzeń w planach"),
    (22, "22 wydarzenia w planach"),
])
def test_plans_caption_polish_plural(going, expected):
    assert plans_caption(going) == expected


def test_logo_files_exist():
    for path in (LOGO_PATH, LOGO_MARK_PATH):
        assert Path(path).read_text(encoding="utf-8").lstrip().startswith("<svg")


@pytest.mark.parametrize("today, preset, expected", [
    (date(2026, 10, 1), "today", (date(2026, 10, 1), date(2026, 10, 1))),
    (date(2026, 10, 1), "tomorrow", (date(2026, 10, 2), date(2026, 10, 2))),
    (date(2026, 10, 1), "weekend", (date(2026, 10, 3), date(2026, 10, 4))),     # czwartek -> sob–nd
    (date(2026, 10, 3), "weekend", (date(2026, 10, 3), date(2026, 10, 4))),     # sobota -> dziś i jutro
    (date(2026, 10, 4), "weekend", (date(2026, 10, 4), date(2026, 10, 4))),     # niedziela -> tylko dziś
    (date(2026, 10, 1), "7d", (date(2026, 10, 1), date(2026, 10, 8))),
    (date(2026, 10, 1), "14d", (date(2026, 10, 1), date(2026, 10, 15))),
    (date(2026, 10, 1), "any", (date(2026, 10, 1), None)),
    (date(2026, 10, 1), None, (date(2026, 10, 1), None)),                       # odznaczony preset
])
def test_date_presets(today, preset, expected):
    assert date_range_for(preset, today) == expected


def test_custom_date_range_handles_incomplete_selection():
    today = date(2026, 10, 1)
    assert date_range_for("custom", today, (date(2026, 10, 5),)) == (date(2026, 10, 5), date(2026, 10, 5))
    assert date_range_for("custom", today, (date(2026, 10, 5), date(2026, 10, 9))) == (
        date(2026, 10, 5), date(2026, 10, 9))
    assert date_range_for("custom", today, ()) == (today, today + timedelta(days=14))


def test_full_date_polish():
    assert full_date(_event(start=datetime(2026, 9, 19, 18))) == "sobota, 19 września 2026"
    multi = _event(start=datetime(2026, 9, 19, 10), end=datetime(2026, 10, 4, 18))
    assert full_date(multi) == "19 września – 4 października 2026"


def test_sort_events():
    a = _event(id="a", start=datetime(2026, 10, 5, 18), price_pln=40, lat=50.0614, lon=19.9366)
    b = _event(id="b", start=datetime(2026, 10, 4, 18), price_pln=0, lat=50.0920, lon=19.9300)
    c = _event(id="c", start=datetime(2026, 10, 6, 18), price_pln=None, lat=50.0515, lon=19.9455)
    events = [a, b, c]
    ids = lambda evs: [e.id for e in evs]                                        # noqa: E731
    assert ids(sort_events(events, "soon", counts={}, center=None)) == ["b", "a", "c"]
    assert ids(sort_events(events, "popular", counts={"c": 5, "a": 2}, center=None)) == ["c", "a", "b"]
    assert ids(sort_events(events, "cheap", counts={}, center=None)) == ["b", "a", "c"]   # nieznana na końcu
    assert ids(sort_events(events, "near", counts={}, center=PLACES["Kazimierz"])) == ["c", "a", "b"]


def test_event_card_is_escaped_and_shows_distance():
    event = _event(title='<b>Jazz</b> "noc"', venue="Klub <x>", tags=["jazz"],
                   image_url="https://x.pl/a'b.jpg")
    card = event_card_html(event, going=3, distance=1.24, today=date(2026, 10, 3))
    assert "<b>Jazz</b>" not in card and "&lt;b&gt;Jazz&lt;/b&gt;" in card
    assert "Klub &lt;x&gt;" in card and "a%27b.jpg" in card
    assert "1,2 km" in card and "3 osoby idą" in card and ">dziś<" in card


def test_clear_filters_restores_defaults(app_storage):
    at = _run_app()
    default_count = _results_count(at)
    at.text_input(key="m1_f_query_0").input("zzzzqqq").run()
    assert at.session_state["filters"].query == "zzzzqqq"
    assert _results_count(at) == 0

    at.button(key="m1_f_clear").click().run()
    today = date.today()
    assert at.session_state["filters"] == FilterCriteria(date_from=today, date_to=today + timedelta(days=14))
    # Nowa wersja kluczy = świeże widgety z wartościami domyślnymi (bez rozjazdu z przeglądarką).
    assert at.text_input(key="m1_f_query_1").value == ""
    assert _results_count(at) == default_count
    assert not at.exception


def test_category_pills_filter_events(app_storage):
    at = _run_app()
    total = _results_count(at)
    at.button_group(key="m1_f_cats_0").set_value([Category.MUSIC]).run()
    music = _results_count(at)
    assert 0 < music < total
    assert at.session_state["filters"].categories == [Category.MUSIC]
    assert not at.exception


def test_radius_limits_events_to_neighbourhood(app_storage):
    at = _run_app()
    total = _results_count(at)
    at.session_state["m1_f_when_0"] = "any"
    at.run()
    everything = _results_count(at)
    assert everything >= total

    at.session_state["m1_f_place_0"] = "Nowa Huta"
    at.session_state["m1_f_radius_0"] = 1.0
    at.run()
    near = _results_count(at)
    assert near < everything
    center = PLACES["Nowa Huta"]
    listed = {b.key.removeprefix("m1_pick_") for b in at.button if (b.key or "").startswith("m1_pick_")}
    for event in app_storage.list_events(at.session_state["filters"]):
        if event.id in listed:
            assert abs(event.lat - center.lat) < 0.02 and abs(event.lon - center.lon) < 0.03
    assert any("1 km od: Nowa Huta" in m.value for m in at.markdown)
    assert not at.exception


def test_card_click_selects_event_and_reopens_panel(app_storage):
    at = _run_app()
    at.session_state["m1_right_toggle"] = True               # panel szczegółów schowany
    at.run()
    card = next(b for b in at.button if (b.key or "").startswith("m1_pick_"))
    event_id = card.key.removeprefix("m1_pick_")
    card.click().run()
    assert at.session_state["selected_event_id"] == event_id
    assert at.session_state["m1_right_toggle"] is False
    assert at.button(key="m1_close_panel")
    assert not at.exception


def test_chat_sheet_keeps_list_filters(app_storage):
    at = _run_app()
    at.toggle(key="m1_f_free_0").set_value(True).run()
    free = _results_count(at)
    at.session_state["selected_event_id"] = "e_jazz_alchemia"
    at.run()
    at.button(key="m1_open_chat").click().run()
    assert at.session_state["view"] == View.CHAT
    assert at.button(key="m5_back")                           # czat w arkuszu nad listą
    at.button(key="m5_back").click().run()
    assert at.session_state["view"] == View.MAP
    assert at.toggle(key="m1_f_free_0").value is True and _results_count(at) == free
    assert not at.exception


def test_menu_action_closes_menu_and_switches_view(app_storage):
    at = _run_app()
    at.session_state["m1_menu"] = True
    at.run()
    labels = [at.button(key=k).label for k in ("m1_menu_profile", "m1_menu_add_event", "m1_menu_reset_btn")]
    assert not any(_EMOJI.search(label) for label in labels)

    at.button(key="m1_menu_profile").click().run()
    assert at.session_state["view"] == View.PROFILE_EDIT
    assert at.session_state["m1_menu"] is False
    assert not at.exception


def test_user_switch_from_m3_closes_menu(app_storage):
    at = _run_app()
    at.session_state["m1_menu"] = True
    at.run()
    at.selectbox(key="m3_user_switch").select("u_kuba").run()
    assert at.session_state["user_id"] == "u_kuba"
    assert at.session_state["m1_menu"] is False
    assert not at.exception


def test_reset_demo_restores_data_and_closes_menu(app_storage):
    room = "event:e_jazz_alchemia"
    before = app_storage.count_messages(room)
    app_storage.post_message(room, "u_ola", "wiadomość testowa")
    at = _run_app()
    at.session_state["m1_menu"] = True
    at.session_state["selected_event_id"] = "e_jazz_alchemia"
    at.run()

    at.button(key="m1_menu_reset_btn").click().run()
    assert app_storage.count_messages(room) == before
    assert at.session_state["selected_event_id"] is None
    assert at.session_state["m1_menu"] is False
    assert [t.value for t in at.toast] == ["Przywrócono dane demo"]
    assert not at.exception


def test_location_place_coordinates_are_in_krakow():
    from shared.models import is_in_krakow

    for name, place in PLACES.items():
        assert isinstance(place, Place) and is_in_krakow(place.lat, place.lon), name
