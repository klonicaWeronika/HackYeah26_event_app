"""
M2 (opcjonalne) — formularz dodawania własnego wydarzenia przez użytkownika.

Włączany flagą FEATURES["add_event"] w shared/config.py, gdy spełni DoD z TASK_SPEC.md.
Kontrakt: zapisuje Event(source="user", created_by=user.id) przez storage.upsert_event().
"""

from __future__ import annotations

import streamlit as st

from shared import state
from shared.models import User
from shared.state import View
from shared.storage import Storage


def render_add_event_form(storage: Storage, user: User) -> None:
    st.subheader("➕ Dodaj wydarzenie")
    st.info("TODO(M2): formularz -> geocode() -> Event(source='user') -> storage.upsert_event()")
    st.button("← Wróć do mapy", on_click=state.go_to, args=(View.MAP,), key="m2_back")
