"""
M1 — layout aplikacji: górny pasek, lewy panel filtrów, prawy panel szczegółów wydarzenia.

Układ (wireframe):
    ┌──────────── header: awatar + nazwa ─────────────── ⚙️ Opcje ┐
    │ sidebar:  │  MAPA z pinezkami  /  Live Chat  │ prawy panel:  │
    │ filtry    │  (View.MAP / View.CHAT / ...)    │ szczegóły +   │
    │           │                                  │ dopasowania + │
    │           │                                  │ przycisk czatu│
    └───────────┴──────────────────────────────────┴───────────────┘
"""

from __future__ import annotations

import html
from datetime import date, timedelta

import streamlit as st

from m1_ui_map.map_view import MAP_HEIGHT, reset_map
from m3_profile.views import avatar_html, render_user_card, render_user_switcher
from m4_matching.engine import match_for_event
from m4_matching.widgets import render_recommendations
from m5_chat.chat_view import render_attendance_controls
from shared import state
from shared.config import APP_NAME, APP_TAGLINE, FEATURES, MAX_MATCHES_IN_PANEL
from shared.formatting import format_price, format_when
from shared.models import CATEGORY_META, Category, Event, FilterCriteria, User, event_room_id
from shared.state import View
from shared.storage import Storage

_FILTER_KEYS = ("m1_f_query", "m1_f_cats", "m1_f_dates", "m1_f_tags", "m1_f_free")


def inject_css() -> None:
    st.markdown(
        """
        <style>
          .block-container {padding-top: 1.2rem; padding-bottom: 0.5rem;}
          header[data-testid="stHeader"] {height: 0; background: transparent;}
          .m1-header {display:flex; align-items:center; gap:12px;}
          .m1-header .name {font-weight:600; font-size:1.05rem;}
          .m1-header .sub {color:#888; font-size:0.8rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Górny pasek
# --------------------------------------------------------------------------- #

def render_header(storage: Storage, user: User) -> None:
    col_user, col_options = st.columns([6, 1], vertical_alignment="center")
    with col_user:
        going = len(storage.list_user_attendance(user.id))
        st.markdown(
            f'<div class="m1-header">{avatar_html(user, 40)}'
            f'<div><div class="name">{html.escape(user.name)}</div>'
            f'<div class="sub">Zapisany(a) na {going} wydarzeń</div></div></div>',
            unsafe_allow_html=True,
        )
    with col_options, st.popover("⚙️ Opcje", width="stretch"):
        st.button("✏️ Edytuj profil", on_click=state.go_to, args=(View.PROFILE_EDIT,), width="stretch")
        if FEATURES["add_event"]:
            st.button("➕ Dodaj wydarzenie", on_click=state.go_to, args=(View.ADD_EVENT,), width="stretch")
        render_user_switcher(storage)
        if st.button("🔄 Reset danych demo", width="stretch"):
            storage.reset()
            state.select_event(None)
            st.rerun()


# --------------------------------------------------------------------------- #
# Lewy panel — filtry
# --------------------------------------------------------------------------- #

def _clear_filters() -> None:
    for key in _FILTER_KEYS:
        st.session_state.pop(key, None)


def render_filters(storage: Storage) -> FilterCriteria:
    today = date.today()
    with st.sidebar:
        st.markdown(f"## 📍 {APP_NAME}")
        st.caption(APP_TAGLINE)
        st.markdown("### Filtry")

        query = st.text_input("Szukaj", key="m1_f_query", placeholder="np. jazz, Kazimierz…")
        categories = st.pills(
            "Kategorie", list(Category), selection_mode="multi", key="m1_f_cats",
            format_func=lambda c: f"{CATEGORY_META[c].emoji} {CATEGORY_META[c].label}",
        )
        dates = st.date_input(
            "Kiedy", value=(today, today + timedelta(days=14)), key="m1_f_dates", format="DD.MM.YYYY",
        )
        tags = st.multiselect("Zainteresowania", storage.known_tags(), key="m1_f_tags")
        free_only = st.toggle("Tylko darmowe", key="m1_f_free")
        st.button("Wyczyść filtry", on_click=_clear_filters, type="tertiary")

    date_range = list(dates) if isinstance(dates, (list, tuple)) else [dates]
    criteria = FilterCriteria(
        query=query,
        categories=categories or [],
        date_from=date_range[0] if date_range else None,
        date_to=date_range[1] if len(date_range) > 1 else (date_range[0] if date_range else None),
        tags=tags,
        free_only=free_only,
    )
    state.set_filters(criteria)
    return criteria


# --------------------------------------------------------------------------- #
# Prawy panel — szczegóły wydarzenia
# --------------------------------------------------------------------------- #

def _close_panel() -> None:
    state.select_event(None)
    reset_map()


def render_event_panel(storage: Storage, user: User, event: Event | None) -> None:
    with st.container(height=MAP_HEIGHT, border=False):
        if event is None:
            st.info("👈 Kliknij pinezkę na mapie, aby zobaczyć szczegóły wydarzenia i osoby, które się na nie wybierają.")
            if FEATURES["recommendations"]:
                render_recommendations(storage, user)
            return

        meta = event.meta
        col_badge, col_close = st.columns([5, 1], vertical_alignment="center")
        col_badge.badge(f"{meta.emoji} {meta.label}", color="primary")
        col_close.button("✕", key="m1_close_panel", on_click=_close_panel, type="tertiary", help="Zamknij")

        st.markdown(f"### {event.title}")
        st.markdown(
            f"🗓️ **{format_when(event)}**  \n"
            f"📍 **{event.venue}**, {event.address}  \n"
            f"💸 {format_price(event.price_pln)} · 👥 {len(storage.list_attendees(event.id))} zapisanych"
        )
        if event.description:
            st.caption(event.description)
        if event.url:
            st.link_button("Strona wydarzenia ↗", event.url)

        render_attendance_controls(storage, event, user)

        room_id = event_room_id(event.id)
        st.button(
            f"💬 Czat wydarzenia ({storage.count_messages(room_id)})",
            key="m1_open_chat", width="stretch",
            on_click=state.go_to, args=(View.CHAT,), kwargs={"room_id": room_id},
        )

        st.markdown("#### 🤝 Pasujące osoby")
        matches = match_for_event(storage, user, event.id, limit=MAX_MATCHES_IN_PANEL)
        if not matches:
            st.caption("Nikt jeszcze się nie zapisał (albo nie chce być widoczny). Bądź pierwszy!")
        for match in matches:
            render_user_card(match.user, match, key=f"m1_match_{event.id}_{match.user.id}")
