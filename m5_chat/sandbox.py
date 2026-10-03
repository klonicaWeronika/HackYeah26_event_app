"""
M5 sandbox — czat w izolacji:  streamlit run m5_chat/sandbox.py

Test "na żywo": otwórz dwie karty
    http://localhost:8501/?user=u_ola
    http://localhost:8501/?user=u_kuba
i pisz z obu — wiadomości pojawiają się po <= CHAT_POLL_SECONDS.
Klik w awatar/imię autora -> profil (M3); „← Wróć do mapy” wraca tu do czatu.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from m3_profile.views import render_profile_view  # noqa: E402
from m5_chat.chat_view import render_attendance_controls, render_chat_room  # noqa: E402
from shared import state  # noqa: E402
from shared.models import event_room_id  # noqa: E402
from shared.state import View  # noqa: E402
from shared.storage import get_storage  # noqa: E402

st.set_page_config(page_title="M5 sandbox", layout="wide")
storage = get_storage()
state.init()

user = storage.get_user(state.current_user_id())
events = {e.id: e for e in storage.list_events()}
event_id = st.sidebar.selectbox("Pokój wydarzenia", list(events), format_func=lambda eid: events[eid].title)
st.sidebar.write(f"Jesteś: **{user.name}** (`?user={user.id}`)")
with st.sidebar:
    render_attendance_controls(storage, events[event_id], user)

if state.current_view() is View.PROFILE_VIEW and (viewed := storage.get_user(state.viewed_user_id())):
    render_profile_view(storage, viewed)
else:
    render_chat_room(storage, user, event_room_id(event_id))
