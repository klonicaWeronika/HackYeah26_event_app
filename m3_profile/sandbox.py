"""M3 sandbox — praca nad profilem w izolacji:  streamlit run m3_profile/sandbox.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from m3_profile.views import render_profile_editor, render_profile_view, render_user_card, render_user_switcher  # noqa: E402
from shared import state  # noqa: E402
from shared.storage import get_storage  # noqa: E402

st.set_page_config(page_title="M3 sandbox", layout="wide")
storage = get_storage()
state.init()

with st.sidebar:
    render_user_switcher(storage)
    # data URI zdjęcia ma dziesiątki KB — skracamy długie wartości, żeby podgląd stanu był czytelny
    preview = ", ".join(
        f"{k}: {r if len(r := repr(v)) <= 80 else r[:77] + '…'}" for k, v in sorted(st.session_state.items())
    )
    st.caption(f"session_state: `{{{preview}}}`")

user = storage.get_user(state.current_user_id())
tab_edit, tab_cards, tab_view = st.tabs(["Edycja profilu", "Karty osób", "Podgląd profilu"])
with tab_edit:
    render_profile_editor(storage, user)
with tab_cards:
    for other in storage.list_users():
        render_user_card(other, key=f"sb_card_{other.id}")
with tab_view:
    render_profile_view(storage, storage.get_user(state.viewed_user_id() or user.id))
