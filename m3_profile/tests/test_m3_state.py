"""M3-01 — kontrakt shared/state.py (jedyne źródło kluczy sesji współdzielonych).

Zachowanie sprawdzamy w prawdziwym runtime Streamlit (AppTest.from_function, bez przeglądarki),
a akcje wywołujemy tak jak moduły: przez callbacki `on_click` przycisków.
"""

from __future__ import annotations

import inspect
import os
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from shared import state
from shared.config import DEFAULT_USER_ID
from shared.models import Category, FilterCriteria
from shared.state import Keys, View

ROOT = Path(__file__).resolve().parents[2]


def _state_app() -> None:
    """Minimalna aplikacja: state.init() + przyciski wywołujące API stanu (jak w modułach)."""
    import streamlit as st

    from shared import state
    from shared.models import Category, FilterCriteria
    from shared.state import View

    state.init()
    st.button("as Kuba", key="t_user", on_click=state.set_current_user, args=("u_kuba",))
    st.button("chat", key="t_chat", on_click=state.go_to, args=(View.CHAT,),
              kwargs={"room_id": "event:e_jazz_alchemia"})
    st.button("profile", key="t_profile", on_click=state.go_to, args=(View.PROFILE_VIEW,),
              kwargs={"user_id": "u_bartek"})
    st.button("map", key="t_map", on_click=state.go_to, args=(View.MAP,))
    st.button("select", key="t_select", on_click=state.select_event, args=("e_jazz_alchemia",))
    st.button("unselect", key="t_unselect", on_click=state.select_event, args=(None,))
    st.button("filters", key="t_filters", on_click=state.set_filters,
              args=(FilterCriteria(categories=[Category.MUSIC]),))
    # Odczyt wyłącznie przez gettery — dowód, że API zwraca to, co zapisały settery.
    st.text(
        f"user={state.current_user_id()}|view={state.current_view().value}|room={state.chat_room_id()}"
        f"|viewed={state.viewed_user_id()}|event={state.selected_event_id()}"
        f"|cats={[c.value for c in state.get_filters().categories]}"
    )


def _new_app(query_params: dict | None = None) -> AppTest:
    at = AppTest.from_function(_state_app, default_timeout=10)
    at.query_params.update(query_params or {})
    return at


def _getters(at: AppTest) -> dict[str, str]:
    """Parsuje linię z getterów: {'user': 'u_ola', 'view': 'map', ...}."""
    return dict(part.split("=", 1) for part in at.text[0].value.split("|"))


def _click(at: AppTest, key: str) -> AppTest:
    at.button(key=key).click().run()
    assert not at.exception, at.exception
    return at


# --------------------------------------------------------------------------- #
# init()
# --------------------------------------------------------------------------- #

def test_init_sets_documented_defaults():
    at = _new_app().run()
    assert not at.exception, at.exception
    ss = at.session_state
    assert ss[Keys.USER_ID] == DEFAULT_USER_ID
    assert ss[Keys.VIEW] is View.MAP
    assert ss[Keys.SELECTED_EVENT_ID] is None
    assert ss[Keys.FILTERS] == FilterCriteria()
    assert ss[Keys.CHAT_ROOM_ID] is None
    assert ss[Keys.VIEWED_USER_ID] is None
    assert _getters(at) == {
        "user": DEFAULT_USER_ID, "view": "map", "room": "None", "viewed": "None", "event": "None", "cats": "[]",
    }


def test_init_reads_user_from_url():
    at = _new_app({"user": "u_kuba"}).run()
    assert at.session_state[Keys.USER_ID] == "u_kuba"
    assert _getters(at)["user"] == "u_kuba"


def test_init_is_idempotent_and_keeps_session_values_on_rerun():
    at = _click(_new_app().run(), "t_chat")
    at.run()                                   # kolejny rerun -> init() nie nadpisuje stanu
    assert at.session_state[Keys.VIEW] is View.CHAT
    assert at.session_state[Keys.CHAT_ROOM_ID] == "event:e_jazz_alchemia"


# --------------------------------------------------------------------------- #
# set_current_user()
# --------------------------------------------------------------------------- #

def test_set_current_user_updates_url_and_survives_rerun():
    at = _click(_new_app().run(), "t_user")
    assert at.session_state[Keys.USER_ID] == "u_kuba"
    assert at.query_params.get("user") == "u_kuba"
    at.run()
    assert _getters(at)["user"] == "u_kuba"


def test_user_survives_page_refresh_via_url():
    """Odświeżenie strony = nowa sesja z tym samym URL -> ten sam użytkownik."""
    before = _click(_new_app().run(), "t_user")
    refreshed = _new_app(dict(before.query_params)).run()
    assert refreshed.session_state[Keys.USER_ID] == "u_kuba"


# --------------------------------------------------------------------------- #
# go_to(), select_event(), set_filters()
# --------------------------------------------------------------------------- #

def test_go_to_keeps_room_and_viewed_user_when_not_given():
    at = _click(_new_app().run(), "t_chat")
    assert _getters(at)["view"] == "chat" and _getters(at)["room"] == "event:e_jazz_alchemia"

    _click(at, "t_profile")
    g = _getters(at)
    assert (g["view"], g["viewed"], g["room"]) == ("profile_view", "u_bartek", "event:e_jazz_alchemia")

    _click(at, "t_map")
    g = _getters(at)
    assert (g["view"], g["viewed"], g["room"]) == ("map", "u_bartek", "event:e_jazz_alchemia")


def test_selected_event_and_filters_are_independent_of_view():
    at = _click(_new_app().run(), "t_select")
    _click(at, "t_filters")
    _click(at, "t_chat")                       # zmiana widoku nie zamyka prawego panelu
    g = _getters(at)
    assert (g["event"], g["cats"], g["view"]) == ("e_jazz_alchemia", "['music']", "chat")
    assert at.session_state[Keys.FILTERS] == FilterCriteria(categories=[Category.MUSIC])

    _click(at, "t_unselect")
    assert _getters(at)["event"] == "None"


# --------------------------------------------------------------------------- #
# Zamrożony kontrakt: nazwy kluczy, widoki, sygnatury (zmiany tylko addytywne)
# --------------------------------------------------------------------------- #

SHARED_KEYS = {
    "USER_ID": "user_id", "VIEW": "view", "SELECTED_EVENT_ID": "selected_event_id",
    "FILTERS": "filters", "CHAT_ROOM_ID": "chat_room_id", "VIEWED_USER_ID": "viewed_user_id",
}
VIEWS = {
    "MAP": "map", "CHAT": "chat", "PROFILE_EDIT": "profile_edit",
    "PROFILE_VIEW": "profile_view", "ADD_EVENT": "add_event",
}
SIGNATURES = {           # ARCHITECTURE §5.2 / TASK_SPEC M3 §3.2 — wolno dodawać, nie wolno zmieniać
    "init": "(default_user_id: 'str' = 'u_ola') -> 'None'",
    "current_user_id": "() -> 'str'",
    "set_current_user": "(user_id: 'str') -> 'None'",
    "current_view": "() -> 'View'",
    "go_to": "(view: 'View', *, room_id: 'str | None' = None, user_id: 'str | None' = None) -> 'None'",
    "chat_room_id": "() -> 'str | None'",
    "viewed_user_id": "() -> 'str | None'",
    "selected_event_id": "() -> 'str | None'",
    "select_event": "(event_id: 'str | None') -> 'None'",
    "get_filters": "() -> 'FilterCriteria'",
    "set_filters": "(criteria: 'FilterCriteria') -> 'None'",
}


def test_existing_keys_and_views_are_unchanged():
    for name, value in SHARED_KEYS.items():
        assert getattr(Keys, name) == value, f"Keys.{name} zmieniony — zmiany tylko addytywne"
    for name, value in VIEWS.items():
        assert View[name].value == value, f"View.{name} zmieniony — zmiany tylko addytywne"


@pytest.mark.parametrize("name", sorted(SIGNATURES))
def test_public_api_signatures_are_frozen(name):
    assert str(inspect.signature(getattr(state, name))) == SIGNATURES[name]


# --------------------------------------------------------------------------- #
# „Nikt nie używa gołych kluczy współdzielonych” (DoD M3-01) — skan kodu modułów
# --------------------------------------------------------------------------- #

_KEY_ALT = "|".join(sorted(SHARED_KEYS.values()))
_BARE_KEY_PATTERNS = [
    # st.session_state["view"], .get("view"), .setdefault("view"), .pop("view")
    re.compile(rf"""session_state\s*(?:\[|\.(?:get|setdefault|pop)\()\s*["'](?:{_KEY_ALT})["']"""),
    # st.session_state.view
    re.compile(rf"session_state\.(?:{_KEY_ALT})\b"),
    # widget z key="filters" nadpisałby klucz współdzielony
    re.compile(rf"""\bkey\s*=\s*["'](?:{_KEY_ALT})["']"""),
    # ?user= w URL ustawia/czyta tylko state.py
    re.compile(r"""query_params\s*(?:\[|\.(?:get|setdefault|pop)\()\s*["']user["']"""),
]


def _module_sources() -> list[Path]:
    """Pliki .py aplikacji (bez testów i state.py). os.walk z przycinaniem — nie wchodzimy do .venv."""
    skip_dirs = {"tests", "__pycache__", "node_modules", "data"}
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".") and d != "venv"]
        out += [Path(dirpath, f) for f in filenames if f.endswith(".py")]
    return [p for p in out if p != ROOT / "shared" / "state.py"]


def test_no_module_uses_bare_shared_session_keys():
    offenders = [
        f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}"
        for path in _module_sources()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if any(p.search(line) for p in _BARE_KEY_PATTERNS)
    ]
    assert not offenders, "Użyj shared.state zamiast gołych kluczy:\n" + "\n".join(offenders)


def test_bare_key_scanner_detects_violations():
    """Strażnik strażnika: skaner faktycznie łapie typowe naruszenia (i nie łapie kluczy m1_…)."""
    bad = ['st.session_state["view"] = "map"', "st.session_state.get('user_id')",
           "st.session_state.filters", 'st.selectbox("x", [], key="filters")', 'st.query_params["user"] = u']
    ok = ['st.session_state["m1_map_nonce"] = 1', 'st.button("x", key="m3_view_btn")', "state.current_view()"]
    assert all(any(p.search(line) for p in _BARE_KEY_PATTERNS) for line in bad)
    assert not any(p.search(line) for p in _BARE_KEY_PATTERNS for line in ok)
