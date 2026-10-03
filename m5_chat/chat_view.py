"""
M5 — UI czatu i interakcji społecznościowych.

Czat z pollingiem przez @st.fragment(run_every=...) — odświeża się TYLKO okienko czatu,
a nie cała aplikacja (mapa się nie przeładowuje).
Układ: kolejne wiadomości jednej osoby to grupa. Cudze grupy po lewej, z klikalnym awatarem
i imieniem (-> profil autora); własne po prawej, w kolorze akcentu. Tekst w dymkach
przez html.escape -> zawsze dosłownie.
"""

from __future__ import annotations

import html
import time
import zlib
from collections.abc import Iterable

import streamlit as st

from m5_chat.service import (
    BUFFER_LIMIT, css_string, escape_markdown, group_messages, refresh_messages, room_title, safe_avatar_src,
    send_message,
)
from shared import state
from shared.config import CHAT_POLL_SECONDS, FEATURES
from shared.formatting import format_time
from shared.models import ChatMessage, Event, User
from shared.state import View
from shared.storage import Storage

AVATAR_SIZE = 36
# Rysowanie wiadomości to większość kosztu ticka -> pokazujemy ostatnie N, starsze na żądanie.
SHOW_STEP = 50
# Te same kolory co awatary z inicjałami w m3_profile.views (ta sama osoba = ten sam kolor wszędzie).
_AVATAR_COLORS = ["#E4572E", "#17BEBB", "#FFC914", "#2E282A", "#76B041", "#7E5BEF", "#F46197"]

# Nagłówek cudzej grupy = JEDEN st.button (tertiary) z imieniem; awatar rysuje CSS w `::before`
# (kolor/zdjęcie/inicjały per osoba przez klasę `st-key-<key>`). Mniej elementów = szybszy tick.
# Kolory dymków półprzezroczyste -> czytelne w jasnym i ciemnym motywie.
_BASE_CSS = f"""
.st-key-m5_css {{display: none;}}
[class*="st-key-m5_av"] button {{gap: 8px; min-height: {AVATAR_SIZE}px;}}
[class*="st-key-m5_av"] button::before {{
  content: "?"; flex: 0 0 {AVATAR_SIZE}px; width: {AVATAR_SIZE}px; height: {AVATAR_SIZE}px;
  display: flex; align-items: center; justify-content: center; border-radius: 50%;
  background: #9e9e9e center / cover no-repeat; color: #fff; font-weight: 600; font-size: 14px;
}}
[class*="st-key-m5_av"] button:hover::before {{filter: brightness(0.9);}}
[class*="st-key-m5_av"] button:disabled {{opacity: 1; cursor: default;}}
[class*="st-key-m5_older_"] {{margin-bottom: 8px;}}
.m5-bubbles {{display: flex; flex-direction: column; align-items: flex-start; gap: 3px; margin: 2px 0 14px;}}
.m5-bubbles.m5-theirs {{margin-left: {AVATAR_SIZE + 8}px;}}
.m5-bubbles.m5-mine {{align-items: flex-end;}}
.m5-bubble {{
  max-width: 80%; padding: 6px 12px; border-radius: 16px; line-height: 1.45;
  white-space: pre-wrap; overflow-wrap: anywhere; background: rgba(128, 128, 128, 0.14);
}}
.m5-mine .m5-bubble {{background: rgba(228, 87, 46, 0.18);}}
.m5-time {{float: right; margin: 5px 0 0 10px; font-size: 0.72em; opacity: 0.6; white-space: nowrap;}}
.m5-empty {{text-align: center; padding: 64px 16px; opacity: 0.7;}}
.m5-empty-icon {{font-size: 2.4rem;}}
"""

_EMPTY_HTML = (
    '<div class="m5-empty"><div class="m5-empty-icon">💬</div>'
    "Jeszcze cisza…<br>Napisz pierwszą wiadomość 👋</div>"
)


def _avatar_key_prefix(user_id: str) -> str:
    """Prefiks klucza przycisku-nagłówka: stały dla osoby i bezpieczny w CSS (hash zamiast surowego ID)."""
    return f"m5_av{zlib.crc32(user_id.encode()):08x}_"


def _author_css(author: User) -> str:
    """Awatar jednej osoby: inicjały, kolor, zdjęcie (raz na osobę, a nie przy każdej wiadomości)."""
    selector = f'[class*="st-key-{_avatar_key_prefix(author.id)}"] button::before'
    color = _AVATAR_COLORS[zlib.crc32(author.id.encode()) % len(_AVATAR_COLORS)]
    rules = f'content: "{css_string(author.initials)}"; background-color: {color};'
    if src := safe_avatar_src(author.avatar_url):
        rules += f'background-image: url("{src}"); color: transparent;'
    return f"{selector} {{{rules}}}"


def _inject_css(authors: Iterable[User]) -> None:
    with st.container(key="m5_css"):
        css = _BASE_CSS + "\n".join(_author_css(a) for a in authors)
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _bubbles_html(messages: list[ChatMessage], *, mine: bool) -> str:
    """Dymki jednej grupy (jeden element st.html). Tekst przez html.escape -> bez HTML i markdownu."""
    bubbles = "".join(
        f'<div class="m5-bubble" title="{m.created_at:%d.%m.%Y %H:%M}">{html.escape(m.text)}'
        f'<span class="m5-time">{html.escape(format_time(m.created_at))}</span></div>'
        for m in messages
    )
    return f'<div class="m5-bubbles {"m5-mine" if mine else "m5-theirs"}">{bubbles}</div>'


def _render_group(group: list[ChatMessage], author: User | None, *, can_open_profile: bool) -> bool:
    """Cudza grupa: nagłówek [awatar] imię (jeden przycisk -> profil), pod nim dymki.

    Zwraca True, gdy kliknięto nagłówek (awatar albo imię autora).
    """
    first = group[0]
    name = author.name if author else "Nieznana osoba"
    clickable = can_open_profile and author is not None
    clicked = st.button(
        f"**{escape_markdown(name)}**", key=f"{_avatar_key_prefix(first.user_id)}{first.id}", type="tertiary",
        help=f"Zobacz profil: {escape_markdown(name)}" if clickable else None, disabled=not clickable,
    )
    st.html(_bubbles_html(group, mine=False))
    return clicked


def render_chat_room(storage: Storage, user: User, room_id: str, *, height: int = 520) -> None:
    """Pełny widok czatu w środkowym obszarze (zamiast mapy)."""
    col_back, col_title = st.columns([1, 5], vertical_alignment="center")
    with col_back:
        st.button("← Mapa", on_click=state.go_to, args=(View.MAP,), key="m5_back")
    with col_title:
        st.markdown(f"### {room_title(storage, room_id)}")

    buf_key, show_key = f"m5_buf_{room_id}", f"m5_show_{room_id}"
    # Ten kod NIE wykonuje się w tickach fragmentu, tylko przy pełnym rerunie (wejście do pokoju,
    # „Reset demo”, zmiana użytkownika) -> wtedy bufor ładujemy od nowa; ticki dociągają tylko nowości.
    st.session_state[buf_key] = storage.list_messages(room_id, limit=BUFFER_LIMIT)

    @st.fragment(run_every=CHAT_POLL_SECONDS)
    def _live_chat() -> None:
        started = time.perf_counter()
        buffer = refresh_messages(storage, room_id, st.session_state.get(buf_key, []))
        st.session_state[buf_key] = buffer
        visible = buffer[-st.session_state.get(show_key, SHOW_STEP):]
        authors = storage.get_users({m.user_id for m in visible})
        can_open_profile = FEATURES["profile_view"]
        _inject_css(a for a in authors.values() if a.id != user.id)   # własny awatar nie jest wyświetlany

        opened_user_id: str | None = None
        # autoscroll trzyma dół tylko, gdy użytkownik sam nie przewinął w górę. Odstępy grup daje CSS (gap=None).
        with st.container(height=height, autoscroll=True, gap=None):
            if len(visible) < len(buffer):
                st.button(
                    "⬆ Pokaż starsze", key=f"m5_older_{room_id}", type="tertiary",
                    on_click=_show_more, args=(show_key, len(visible)),
                )
            if not visible:
                st.html(_EMPTY_HTML)
            for group in group_messages(visible):
                author_id = group[0].user_id
                if author_id == user.id:
                    st.html(_bubbles_html(group, mine=True))
                elif _render_group(group, authors.get(author_id), can_open_profile=can_open_profile):
                    opened_user_id = author_id
        if opened_user_id:
            state.go_to(View.PROFILE_VIEW, user_id=opened_user_id)
            st.rerun()  # pełny rerun: wybór widoku (app.py) jest poza fragmentem

        text = st.chat_input("Napisz wiadomość…", key=f"m5_input_{room_id}", max_chars=500)
        if text:
            send_message(storage, room_id, user.id, text)
            st.rerun(scope="fragment")

        st.session_state["m5_tick_ms"] = tick_ms = (time.perf_counter() - started) * 1000
        if st.query_params.get("m5_debug"):
            st.caption(f"⏱ tick {tick_ms:.1f} ms · bufor {len(buffer)} · widocznych {len(visible)}")

    _live_chat()


def _show_more(show_key: str, shown: int) -> None:
    st.session_state[show_key] = shown + SHOW_STEP


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
