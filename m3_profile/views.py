"""
M3 — profil użytkownika: awatar, karta osoby, edycja i podgląd profilu, przełącznik użytkownika.

SZKIELET (walking skeleton): działa na mockach od godziny 0.
Zakres do zrobienia: m3_profile/TASK_SPEC.md
"""

from __future__ import annotations

import html
import zlib

import streamlit as st

from shared import state
from shared.config import FEATURES
from shared.formatting import format_when
from shared.models import INTEREST_TAGS, MatchResult, User
from shared.storage import Storage
from shared.state import View

_AVATAR_COLORS = ["#E4572E", "#17BEBB", "#FFC914", "#2E282A", "#76B041", "#7E5BEF", "#F46197"]


def avatar_html(user: User, size: int = 40) -> str:
    """Okrągły awatar (zdjęcie albo inicjały). Bezpieczny: escapuje dane użytkownika."""
    style = f"width:{size}px;height:{size}px;border-radius:50%;flex-shrink:0;"
    if user.avatar_url:
        src = html.escape(user.avatar_url, quote=True)
        return f'<img src="{src}" alt="" style="{style}object-fit:cover;">'
    color = _AVATAR_COLORS[zlib.crc32(user.id.encode()) % len(_AVATAR_COLORS)]
    return (
        f'<div style="{style}background:{color};color:#fff;display:flex;align-items:center;'
        f'justify-content:center;font-weight:600;font-size:{size * 0.4:.0f}px;">'
        f"{html.escape(user.initials)}</div>"
    )


def render_avatar(user: User, size: int = 40, caption: str | None = None) -> None:
    label = f'<span style="font-weight:600;">{html.escape(caption)}</span>' if caption else ""
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;">{avatar_html(user, size)}{label}</div>',
        unsafe_allow_html=True,
    )


def render_user_switcher(storage: Storage, key: str = "m3_user_switch") -> None:
    """'Zaloguj jako…' — w MVP nie ma haseł; wybór osoby z bazy."""
    users = storage.list_users()
    ids = [u.id for u in users]
    names = {u.id: u.name for u in users}
    current = state.current_user_id()

    def _on_change() -> None:
        state.set_current_user(st.session_state[key])
        state.select_event(None)

    st.selectbox(
        "Zaloguj jako",
        ids,
        index=ids.index(current) if current in ids else 0,
        format_func=names.get,
        key=key,
        on_change=_on_change,
    )


def render_user_card(user: User, match: MatchResult | None = None, *, key: str) -> None:
    """Kompaktowa karta osoby (lista dopasowań w prawym panelu, lista uczestników)."""
    with st.container(border=True):
        col_avatar, col_body = st.columns([1, 4], vertical_alignment="center")
        with col_avatar:
            st.markdown(avatar_html(user, 44), unsafe_allow_html=True)
        with col_body:
            title = f"**{user.name}**"
            if match is not None:
                title += f" · {match.score:.0%} dopasowania"
            st.markdown(title)
            if match and match.reason:
                st.caption(match.reason)
            elif user.bio:
                st.caption(user.bio[:90])
        if FEATURES["profile_view"]:
            st.button(
                "Zobacz profil", key=key, type="tertiary",
                on_click=state.go_to, args=(View.PROFILE_VIEW,), kwargs={"user_id": user.id},
            )


def render_profile_editor(storage: Storage, user: User) -> None:
    """Edycja własnego profilu. TODO(M3): upload zdjęcia (st.file_uploader -> resize -> data URI)."""
    st.subheader("✏️ Twój profil")
    render_avatar(user, 72, caption=user.name)

    with st.form("m3_profile_form"):
        name = st.text_input("Imię / nick", value=user.name, max_chars=60)
        bio = st.text_area("Kilka słów o sobie", value=user.bio, max_chars=280)
        options = sorted(set(INTEREST_TAGS) | set(storage.known_tags()) | set(user.tags))
        tags = st.multiselect("Zainteresowania", options, default=user.tags, accept_new_options=True)
        avatar_url = st.text_input("URL zdjęcia (tymczasowo)", value=user.avatar_url or "")
        saved = st.form_submit_button("Zapisz", type="primary")

    if saved:
        if not name.strip():
            st.error("Imię nie może być puste.")
            return
        storage.upsert_user(user.copy_with(
            name=name.strip(), bio=bio.strip(), tags=tags, avatar_url=avatar_url.strip() or None,
        ))
        st.toast("Profil zapisany ✅")
        state.go_to(View.MAP)
        st.rerun()

    st.button("← Wróć do mapy", on_click=state.go_to, args=(View.MAP,))


def render_profile_view(storage: Storage, user: User) -> None:
    """Publiczny profil innej osoby (opcjonalne)."""
    st.button("← Wróć do mapy", on_click=state.go_to, args=(View.MAP,), key="m3_back_from_profile")
    render_avatar(user, 96, caption=user.name)
    if user.bio:
        st.write(user.bio)
    if user.tags:
        st.markdown(" ".join(f"`{t}`" for t in user.tags))

    st.markdown("#### Wybiera się na")
    events = [storage.get_event(a.event_id) for a in storage.list_user_attendance(user.id)]
    for event in sorted((e for e in events if e), key=lambda e: e.start):
        st.markdown(f"- {event.meta.emoji} **{event.title}** — {format_when(event)}")
