"""
M5 sandbox — czat i grupy na wydarzenia w izolacji:  streamlit run m5_chat/sandbox.py

Test "na żywo": otwórz dwie karty
    http://localhost:8501/?user=u_ola
    http://localhost:8501/?user=u_kuba
Grupa: wybierz wydarzenie w panelu bocznym -> „Zbierz ekipę” (lista Idą / Interesuje ich)
-> w drugiej karcie „Ekipy” -> zaproszenie -> „Dołącz”. Kolejne zaproszenie w grupie 2+ osób = głosowanie
na czacie. Na start Ola ma zaproszenie do ekipy na jazz (Kuba, Bartek, Natalia).
Klik w awatar/imię autora -> profil (M3) -> „Napisz” = prywatny czat 1:1 (DM).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from m3_profile.views import render_profile_view  # noqa: E402
from m5_chat.chat_view import render_attendance_controls, render_chat_room  # noqa: E402
from m5_chat.group_view import render_event_chat_entry  # noqa: E402
from m5_chat.inbox import render_group_notifier, render_inbox  # noqa: E402
from m5_chat.service import escape_markdown  # noqa: E402
from shared import state  # noqa: E402
from shared.state import View  # noqa: E402
from shared.storage import get_storage  # noqa: E402

st.set_page_config(page_title="M5 sandbox", layout="wide")
storage = get_storage()
state.init()

user = storage.get_user(state.current_user_id())
events = {e.id: e for e in storage.list_events()}
event_id = st.sidebar.selectbox("Wydarzenie", list(events), format_func=lambda eid: events[eid].title)
st.sidebar.write(f"Jesteś: **{escape_markdown(user.name)}** (`?user={user.id}`)")
with st.sidebar:
    render_inbox(storage, user)
    render_attendance_controls(storage, events[event_id], user)
    render_event_chat_entry(storage, event_id, user)
render_group_notifier(storage, user)

room_id = state.chat_room_id()
if state.current_view() is View.PROFILE_VIEW and (viewed := storage.get_user(state.viewed_user_id())):
    render_profile_view(storage, viewed)
elif state.current_view() is View.CHAT and room_id:
    render_chat_room(storage, user, room_id)
else:
    st.info("Otwórz czat grupy z panelu bocznego albo ze skrzynki „Ekipy”.")
