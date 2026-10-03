"""
Punkt wejścia aplikacji:  streamlit run app.py
Właściciel: M1 (kompozycja). Pozostałe moduły dostarczają funkcje renderujące — tu je tylko składamy.
"""

import streamlit as st

from m1_ui_map.layout import inject_css, render_event_panel, render_filters, render_header
from m1_ui_map.map_view import render_map
from m3_profile.views import render_profile_editor, render_profile_view
from m5_chat.chat_view import render_chat_room
from shared import state
from shared.config import APP_NAME, DEFAULT_USER_ID
from shared.state import View
from shared.storage import get_storage

st.set_page_config(page_title=APP_NAME, page_icon="📍",
                   layout="wide", initial_sidebar_state="expanded")

storage = get_storage()
state.init()

user = storage.get_user(state.current_user_id()
                        ) or storage.get_user(DEFAULT_USER_ID)
if user is None:  # pusta baza bez mocków
    st.error("Brak użytkowników w bazie. Uruchom: python -m shared.storage --reset")
    st.stop()

inject_css()
render_header(storage, user)
criteria = render_filters(storage)
events = storage.list_events(criteria)
st.sidebar.caption(f"Na mapie: **{len(events)}** wydarzeń")

center, right = st.columns([2.6, 1.2], gap="medium")

with center:
    view = state.current_view()
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
        clicked_id = render_map(events)
        if clicked_id:
            # Prawy panel renderuje się PO mapie -> pokaże nowy event w tym samym przebiegu (bez st.rerun).
            state.select_event(clicked_id)

with right:
    render_event_panel(storage, user, storage.get_event(
        state.selected_event_id() or ""))
