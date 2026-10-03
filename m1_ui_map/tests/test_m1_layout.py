"""M1 — header, menu i filtry: logika etykiet + zachowanie w całej aplikacji (AppTest, izolowana baza)."""

import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from m1_ui_map.layout import LOGO_MARK_PATH, LOGO_PATH, category_label, plans_caption
from shared.models import CATEGORY_META, Category, FilterCriteria
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


def test_clear_filters_restores_defaults(app_storage):
    at = _run_app()
    default_count = at.sidebar.caption[0].value
    at.text_input(key="m1_f_query_0").input("zzzzqqq").run()
    assert at.session_state["filters"].query == "zzzzqqq"
    assert at.sidebar.caption[0].value == "Na mapie: **0** wydarzeń"

    at.button(key="m1_f_clear").click().run()
    today = date.today()
    assert at.session_state["filters"] == FilterCriteria(date_from=today, date_to=today + timedelta(days=14))
    # Nowa wersja kluczy = świeże widgety z wartościami domyślnymi (bez rozjazdu z przeglądarką).
    assert at.text_input(key="m1_f_query_1").value == ""
    assert at.sidebar.caption[0].value == default_count
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
