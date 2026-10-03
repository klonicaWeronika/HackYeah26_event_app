"""M4 — widgety UI dla rekomendacji (cienka warstwa nad engine.py)."""

from __future__ import annotations

import html

import streamlit as st

from m3_profile.views import avatar_html
from m4_matching.engine import RecBreakdown, attendance_summary, recommend_top
from shared import state
from shared.formatting import format_price, format_when
from shared.models import User
from shared.storage import Storage

MAX_AVATARS = 3             # tyle twarzy podobnych osób na mini-karcie, reszta tylko w liczbie
_AVATAR_SIZE = 26


def render_recommendations(storage: Storage, user: User, *, limit: int = 5) -> None:
    """'Polecane dla Ciebie' — mini-karty; „Pokaż” ustawia wybrany event (prawy panel pokaże szczegóły)."""
    recs = recommend_top(storage, user, limit=limit)
    st.markdown("#### ✨ Polecane dla Ciebie")
    if not recs:
        st.caption("Uzupełnij zainteresowania w profilu, a coś Ci podpowiemy.")
        return
    for rec in recs:
        _render_card(storage, rec)


def people_html(rec: RecBreakdown, total: int) -> str:
    """Nachodzące na siebie awatary podobnych osób + „Idzie N osób, w tym X pasujących”."""
    faces = "".join(
        f'<span title="{html.escape(p.name, quote=True)}" style="display:inline-flex;'
        f'margin-left:{-8 if i else 0}px;border-radius:50%;box-shadow:0 0 0 2px rgba(255,255,255,.85);">'
        f"{avatar_html(p, _AVATAR_SIZE)}</span>"
        for i, p in enumerate(rec.similar_people[:MAX_AVATARS])
    )
    icon = f'<span style="display:flex;">{faces}</span>' if faces else "👥"
    summary = html.escape(attendance_summary(total, len(rec.similar_people)))
    return (
        '<div style="display:flex;align-items:center;gap:8px;font-size:0.85rem;opacity:0.85;">'
        f"{icon}<span>{summary}</span></div>"
    )


def _render_card(storage: Storage, rec: RecBreakdown) -> None:
    event = rec.event
    with st.container(border=True):
        st.markdown(f"{event.meta.emoji} **{event.title}**")
        st.caption(f"{format_when(event)} · {event.venue} · {format_price(event.price_pln)}")
        if rec.fit_tags:
            st.markdown("✨ " + " ".join(f"`{tag}`" for tag in rec.fit_tags))
        col_people, col_show = st.columns([4, 1], vertical_alignment="center")
        col_people.markdown(people_html(rec, len(storage.list_attendees(event.id))), unsafe_allow_html=True)
        col_show.button(
            "Pokaż", key=f"m4_rec_{event.id}", type="tertiary", help="Pokaż szczegóły na mapie",
            on_click=state.select_event, args=(event.id,),
        )
