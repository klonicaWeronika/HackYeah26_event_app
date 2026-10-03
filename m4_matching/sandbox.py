"""M4 sandbox — strojenie matchingu na żywo:  streamlit run m4_matching/sandbox.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from m4_matching.engine import match_for_event, recommend_events  # noqa: E402
from shared.storage import get_storage  # noqa: E402

st.set_page_config(page_title="M4 sandbox", layout="wide")
storage = get_storage()

users = {u.id: u for u in storage.list_users()}
events = {e.id: e for e in storage.list_events()}
user = users[st.sidebar.selectbox("Użytkownik", list(users), format_func=lambda uid: users[uid].name)]
event_id = st.sidebar.selectbox("Wydarzenie", list(events), format_func=lambda eid: events[eid].title)
st.sidebar.write("Tagi:", ", ".join(user.tags))

col_matches, col_recs = st.columns(2)
with col_matches:
    st.subheader(f"Dopasowania: {events[event_id].title}")
    st.dataframe(
        [{"osoba": m.user.name, "score": m.score, "wspólne": ", ".join(m.shared_tags), "powód": m.reason}
         for m in match_for_event(storage, user, event_id)],
        width="stretch",
    )
with col_recs:
    st.subheader("Rekomendacje")
    st.dataframe(
        [{"event": r.event.title, "score": r.score, "powód": r.reason}
         for r in recommend_events(storage, user, limit=10)],
        width="stretch",
    )
