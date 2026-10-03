"""
M5 — UI czatu i interakcji społecznościowych.

SZKIELET: czat z pollingiem przez @st.fragment(run_every=...) — odświeża się TYLKO
okienko czatu, a nie cała aplikacja (mapa się nie przeładowuje).
Zakres do zrobienia: m5_chat/TASK_SPEC.md
"""

from __future__ import annotations

import streamlit as st

from m5_chat.service import room_title, send_message
from shared import state
from shared.config import CHAT_POLL_SECONDS
from shared.formatting import format_time
from shared.models import Event, User
from shared.state import View
from shared.storage import Storage


def render_chat_room(storage: Storage, user: User, room_id: str, *, height: int = 520) -> None:
    """Pełny widok czatu w środkowym obszarze (zamiast mapy)."""
    col_back, col_title = st.columns([1, 5], vertical_alignment="center")
    with col_back:
        st.button("← Mapa", on_click=state.go_to, args=(View.MAP,), key="m5_back")
    with col_title:
        st.markdown(f"### {room_title(storage, room_id)}")

    @st.fragment(run_every=CHAT_POLL_SECONDS)
    def _live_chat() -> None:
        messages = storage.list_messages(room_id, limit=150)
        authors = storage.get_users({m.user_id for m in messages})
        with st.container(height=height, autoscroll=True):
            if not messages:
                st.caption("Jeszcze cisza… Napisz pierwszą wiadomość 👋")
            for msg in messages:
                author = authors.get(msg.user_id)
                is_me = msg.user_id == user.id
                avatar = author.avatar_url if author and (author.avatar_url or "").startswith("http") else None
                with st.chat_message("user" if is_me else "assistant", avatar=avatar):
                    st.markdown(f"**{author.name if author else '?'}** · {format_time(msg.created_at)}")
                    st.text(msg.text)

        text = st.chat_input("Napisz wiadomość…", key=f"m5_input_{room_id}", max_chars=500)
        if text:
            send_message(storage, room_id, user.id, text)
            st.rerun(scope="fragment")

    _live_chat()


def render_attendance_controls(storage: Storage, event: Event, user: User) -> None:
    """Przycisk 'Idę!' / 'Rezygnuję' + zgoda na pokazanie w dopasowaniach."""
    attendance = storage.get_attendance(user.id, event.id)
    if attendance is None:
        if st.button("🙋 Idę!", key=f"m5_join_{event.id}", type="primary", width="stretch"):
            storage.join_event(user.id, event.id)
            st.rerun()
        return

    col_status, col_leave = st.columns([3, 2], vertical_alignment="center")
    col_status.success("Idziesz ✅")
    if col_leave.button("Rezygnuję", key=f"m5_leave_{event.id}", width="stretch"):
        storage.leave_event(user.id, event.id)
        st.rerun()

    open_to_meet = st.toggle(
        "Pokaż mnie innym w dopasowaniach", value=attendance.open_to_meet, key=f"m5_open_{event.id}",
    )
    if open_to_meet != attendance.open_to_meet:
        storage.join_event(user.id, event.id, status=attendance.status, open_to_meet=open_to_meet)
