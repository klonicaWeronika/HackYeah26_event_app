"""
M5 — UI czatu i interakcji społecznościowych.

SZKIELET: czat z pollingiem przez @st.fragment(run_every=...) — odświeża się TYLKO
okienko czatu, a nie cała aplikacja (mapa się nie przeładowuje).
Zakres do zrobienia: m5_chat/TASK_SPEC.md
"""

from __future__ import annotations

import zlib
from collections.abc import Iterable

import streamlit as st

from m5_chat.service import escape_markdown, room_title, safe_avatar_src, send_message
from shared import state
from shared.config import CHAT_POLL_SECONDS, FEATURES
from shared.formatting import format_time
from shared.models import ChatMessage, Event, User
from shared.state import View
from shared.storage import Storage

AVATAR_SIZE = 36
# Te same kolory co awatary z inicjałami w m3_profile.views (ta sama osoba = ten sam kolor wszędzie).
_AVATAR_COLORS = ["#E4572E", "#17BEBB", "#FFC914", "#2E282A", "#76B041", "#7E5BEF", "#F46197"]

# Awatar i imię to zwykłe st.button (klikalne); wygląd nadajemy przez klasy `st-key-<key>`.
_BASE_CSS = f"""
.st-key-m5_css {{display: none;}}
[class*="st-key-m5_row_"] {{padding: 4px 8px; border-radius: 12px;}}
[class*="st-key-m5_row_me_"] {{background: rgba(228, 87, 46, 0.08);}}
[class*="st-key-m5_av"] button {{
  width: {AVATAR_SIZE}px; height: {AVATAR_SIZE}px; min-height: {AVATAR_SIZE}px; padding: 0;
  border: none !important; border-radius: 50%; font-weight: 600; color: #fff !important;
  background-color: #9e9e9e !important; background-size: cover; background-position: center;
}}
[class*="st-key-m5_av"] button:hover {{filter: brightness(0.9);}}
[class*="st-key-m5_av"] button:disabled, [class*="st-key-m5_name_"] button:disabled {{
  opacity: 1; cursor: default;
}}
"""


def _avatar_key_prefix(user_id: str) -> str:
    """Prefiks klucza przycisku-awatara: stały dla osoby i bezpieczny w CSS (hash zamiast surowego ID)."""
    return f"m5_av{zlib.crc32(user_id.encode()):08x}_"


def _author_css(author: User) -> str:
    """Kolor i zdjęcie awatara jednej osoby (raz na osobę, a nie przy każdej wiadomości)."""
    selector = f'[class*="st-key-{_avatar_key_prefix(author.id)}"] button'
    color = _AVATAR_COLORS[zlib.crc32(author.id.encode()) % len(_AVATAR_COLORS)]
    rules = f"background-color: {color} !important;"
    if src := safe_avatar_src(author.avatar_url):
        rules += f'background-image: url("{src}"); color: transparent !important;'
    return f"{selector}, {selector}:hover, {selector}:focus {{{rules}}}"


def _inject_css(authors: Iterable[User]) -> None:
    with st.container(key="m5_css"):
        css = _BASE_CSS + "\n".join(_author_css(a) for a in authors)
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _render_message(msg: ChatMessage, author: User | None, *, is_me: bool, can_open_profile: bool) -> bool:
    """[awatar] imię · godzina / tekst. Zwraca True, gdy kliknięto awatar albo imię autora."""
    name = author.name if author else "Nieznana osoba"
    clickable = can_open_profile and author is not None
    tip = f"Zobacz profil: {escape_markdown(name)}" if clickable else None
    with st.container(horizontal=True, gap="small", key=f"m5_row_{'me_' if is_me else ''}{msg.id}"):
        clicked = st.button(
            escape_markdown(author.initials if author else "?"),
            key=f"{_avatar_key_prefix(msg.user_id)}{msg.id}", help=tip, disabled=not clickable,
        )
        with st.container(gap=None):
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                clicked |= st.button(
                    f"**{escape_markdown(name)}**",
                    key=f"m5_name_{msg.id}", type="tertiary", help=tip, disabled=not clickable,
                )
                st.caption(format_time(msg.created_at))
            st.text(msg.text)
    return clicked


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
        can_open_profile = FEATURES["profile_view"]
        _inject_css(authors.values())

        opened_user_id: str | None = None
        with st.container(height=height, autoscroll=True):
            if not messages:
                st.caption("Jeszcze cisza… Napisz pierwszą wiadomość 👋")
            for msg in messages:
                author = authors.get(msg.user_id)
                if _render_message(msg, author, is_me=msg.user_id == user.id, can_open_profile=can_open_profile):
                    opened_user_id = msg.user_id
        if opened_user_id:
            state.go_to(View.PROFILE_VIEW, user_id=opened_user_id)
            st.rerun()  # pełny rerun: wybór widoku (app.py) jest poza fragmentem

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
