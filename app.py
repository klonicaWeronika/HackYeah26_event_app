"""
Punkt wejścia aplikacji:  streamlit run app.py
Właściciel: M1 (kompozycja). Pozostałe moduły dostarczają funkcje renderujące — tu je tylko składamy.

Układ: mapa na cały ekran + pływające nad nią: górny pasek (wyszukiwarka, lokalizacja z promieniem),
pasek kategorii, lista wydarzeń (lewy panel), szczegóły (prawy panel), arkusz czatu/profilu.
Kolejność w skrypcie != kolejność na ekranie (wszystko pozycjonuje CSS) — liczy się przepływ danych:
filtry -> wydarzenia -> mapa (klik) -> lista i panel widzą wybór w tym samym przebiegu, bez st.rerun().
"""

import streamlit as st

from m1_ui_map.layout import (
    LOGO_MARK_PATH, apply_picked_point, category_counts, current_location, inject_css, is_dark_theme,
    map_focus, note_map_selection, render_category_bar, render_category_counts, render_event_list,
    render_event_panel, render_filters, render_header, render_list_header, render_pick_banner, sort_events,
)
from m1_ui_map.location import within_radius
from m1_ui_map.map_view import render_map
from m3_profile.views import render_profile_editor, render_profile_view
from m5_chat.chat_view import render_chat_room
from m5_chat.inbox import render_group_notifier
from shared import state
from shared.config import APP_NAME, DEFAULT_USER_ID
from shared.state import View
from shared.storage import get_storage

st.set_page_config(
    page_title=APP_NAME, page_icon=LOGO_MARK_PATH, layout="wide", initial_sidebar_state="collapsed",
)

storage = get_storage()
state.init()

user = storage.get_user(state.current_user_id()) or storage.get_user(DEFAULT_USER_ID)
if user is None:  # pusta baza bez mocków
    st.error("Brak użytkowników w bazie. Uruchom: python -m shared.storage --reset")
    st.stop()

dark = is_dark_theme()
inject_css(dark)

# --- Górny pasek + kategorie (przyklejone do góry) ---------------------------------------------------
with st.container(key="m1_topbar", gap=None):
    render_header(storage, user)
    categories = render_category_bar()
render_pick_banner()
render_group_notifier(storage, user)   # M5: toast o zaproszeniu / głosowaniu z innej karty

# --- Lewy panel: najpierw filtry, karty wypełniamy po mapie (widzą wybór z kliknięcia) ---------------
with st.container(key="m1_left", gap=None):
    st.checkbox("Ukryj listę wydarzeń", key="m1_left_toggle", label_visibility="collapsed")
    with st.container(key="m1_left_body"):
        head = st.container(gap="small")
        list_box = st.container(gap="small")

with head:
    title_box = st.container()
    criteria = render_filters(storage, categories=categories)
_, center, radius_km = location = current_location()
events = within_radius(storage.list_events(criteria), center, radius_km)
with title_box:
    sort = render_list_header(len(events), location)
events = sort_events(events, sort, counts=storage.attendee_counts(), center=center)
render_category_counts(category_counts(storage, criteria, center, radius_km))

# --- Mapa na cały ekran ------------------------------------------------------------------------------
with st.container(key="m1_map"):
    click = render_map(
        events, selected_id=state.selected_event_id(), radius_center=center, radius_km=radius_km,
        focus=map_focus(storage, events, state.selected_event_id(), center, radius_km), dark=dark,
    )
if click.point and st.session_state.get("m1_pick"):
    apply_picked_point(*click.point)
    st.rerun()                     # nowy środek promienia zmienia filtry wyżej na stronie
if click.event_id:
    # Lista i prawy panel renderują się PO mapie -> pokażą nowy event w tym samym przebiegu.
    note_map_selection(click.event_id)

with list_box:
    render_event_list(storage, events, selected_id=state.selected_event_id(), center=center)

# --- Arkusz w miejscu listy: czat / profil / formularz (mapa pod spodem zostaje) ----------------------
view = state.current_view()
if view is not View.MAP:
    with st.container(key="m1_sheet"):
        if view is View.CHAT and state.chat_room_id():
            render_chat_room(storage, user, state.chat_room_id())
        elif view is View.PROFILE_EDIT:
            render_profile_editor(storage, user)
        elif view is View.PROFILE_VIEW and (viewed := storage.get_user(state.viewed_user_id())):
            render_profile_view(storage, viewed)
        elif view is View.ADD_EVENT:
            from m2_scraper.add_event_form import render_add_event_form

            render_add_event_form(storage, user)
        else:
            state.go_to(View.MAP)

# --- Prawy panel: szczegóły / polecane ---------------------------------------------------------------
with st.container(key="m1_right", gap=None):
    st.checkbox("Ukryj panel szczegółów", key="m1_right_toggle", label_visibility="collapsed")
    with st.container(key="m1_right_body"):
        render_event_panel(storage, user, storage.get_event(state.selected_event_id() or ""))
