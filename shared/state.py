"""
shared/state.py — KONTRAKT st.session_state (jedyne miejsce z kluczami sesji).

Nikt nie pisze `st.session_state["cos"]` bezpośrednio dla kluczy współdzielonych —
tylko przez funkcje poniżej. Dzięki temu literówka w kluczu nie rozjedzie 5 modułów.
Klucze PRYWATNE modułu (np. stan widgetu) prefiksujemy nazwą modułu: "m3_...", "m5_...".

Właściciel: M3 (profil i stan sesji). Zmiany: addytywnie, przez PR.
"""

from __future__ import annotations

from enum import Enum

import streamlit as st

from shared.config import DEFAULT_USER_ID
from shared.models import FilterCriteria


class View(str, Enum):
    """Co jest wyświetlane w głównym (środkowym) obszarze."""

    MAP = "map"                    # M1: mapa z pinezkami (domyślny)
    CHAT = "chat"                  # M5: czat pokoju `chat_room_id()`
    PROFILE_EDIT = "profile_edit"  # M3: edycja własnego profilu
    PROFILE_VIEW = "profile_view"  # M3: podgląd profilu `viewed_user_id()`
    ADD_EVENT = "add_event"        # M2: formularz dodania wydarzenia (opcjonalne)


class Keys:
    USER_ID = "user_id"
    VIEW = "view"
    SELECTED_EVENT_ID = "selected_event_id"
    FILTERS = "filters"
    CHAT_ROOM_ID = "chat_room_id"
    VIEWED_USER_ID = "viewed_user_id"


def init(default_user_id: str = DEFAULT_USER_ID) -> None:
    """Wywoływane RAZ na początku app.py / sandboxa. Idempotentne.

    `?user=u_kuba` w URL pozwala otworzyć dwie karty jako dwie różne osoby (demo czatu).
    """
    ss = st.session_state
    if Keys.USER_ID not in ss:
        ss[Keys.USER_ID] = st.query_params.get("user", default_user_id)
    ss.setdefault(Keys.VIEW, View.MAP)
    ss.setdefault(Keys.SELECTED_EVENT_ID, None)
    ss.setdefault(Keys.FILTERS, FilterCriteria())
    ss.setdefault(Keys.CHAT_ROOM_ID, None)
    ss.setdefault(Keys.VIEWED_USER_ID, None)


# --- użytkownik ---------------------------------------------------------- #

def current_user_id() -> str:
    return st.session_state[Keys.USER_ID]


def set_current_user(user_id: str) -> None:
    st.session_state[Keys.USER_ID] = user_id
    st.query_params["user"] = user_id


# --- widok główny -------------------------------------------------------- #

def current_view() -> View:
    return st.session_state[Keys.VIEW]


def go_to(view: View, *, room_id: str | None = None, user_id: str | None = None) -> None:
    """Przełącza środkowy obszar. Wywołuj w callbacku albo przed `st.rerun()`."""
    ss = st.session_state
    ss[Keys.VIEW] = view
    if room_id is not None:
        ss[Keys.CHAT_ROOM_ID] = room_id
    if user_id is not None:
        ss[Keys.VIEWED_USER_ID] = user_id


def chat_room_id() -> str | None:
    return st.session_state[Keys.CHAT_ROOM_ID]


def viewed_user_id() -> str | None:
    return st.session_state[Keys.VIEWED_USER_ID]


# --- wybrany event (prawy panel) ---------------------------------------- #

def selected_event_id() -> str | None:
    return st.session_state[Keys.SELECTED_EVENT_ID]


def select_event(event_id: str | None) -> None:
    st.session_state[Keys.SELECTED_EVENT_ID] = event_id


# --- filtry -------------------------------------------------------------- #

def get_filters() -> FilterCriteria:
    return st.session_state[Keys.FILTERS]


def set_filters(criteria: FilterCriteria) -> None:
    st.session_state[Keys.FILTERS] = criteria
