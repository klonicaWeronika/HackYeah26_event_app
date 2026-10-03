"""M4 — widgety UI dla rekomendacji (cienka warstwa nad engine.py)."""

from __future__ import annotations

import streamlit as st

from m4_matching.engine import recommend_events
from shared import state
from shared.formatting import format_when
from shared.models import User
from shared.storage import Storage


def render_recommendations(storage: Storage, user: User, *, limit: int = 5) -> None:
    """'Polecane dla Ciebie' — klik ustawia wybrany event (prawy panel pokaże szczegóły)."""
    recs = recommend_events(storage, user, limit=limit)
    st.markdown("#### ✨ Polecane dla Ciebie")
    if not recs:
        st.caption("Uzupełnij zainteresowania w profilu, a coś Ci podpowiemy.")
        return
    for rec in recs:
        event = rec.event
        with st.container(border=True):
            st.markdown(f"{event.meta.emoji} **{event.title}**")
            st.caption(f"{format_when(event)} · {event.venue}  \n{rec.reason}")
            st.button(
                "Pokaż", key=f"m4_rec_{event.id}", type="tertiary",
                on_click=state.select_event, args=(event.id,),
            )
