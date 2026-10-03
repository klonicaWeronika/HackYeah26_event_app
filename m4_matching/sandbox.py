"""M4 sandbox — strojenie matchingu na żywo:  streamlit run m4_matching/sandbox.py

Suwaki w panelu bocznym nadpisują WEIGHTS tylko w tej sesji; kolumna „miejsce przy WEIGHTS”
pokazuje, jak ranking zmienił się względem wag zapisanych w engine.py.
Osobna baza dla sandboxa:  EVENTAPP_DB=data/sandbox.db streamlit run m4_matching/sandbox.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from m4_matching.engine import WEIGHTS, match_breakdown, match_reason, recommend_events  # noqa: E402
from shared.mock_data import DEMO_USER_ID  # noqa: E402
from shared.storage import get_storage  # noqa: E402

DEMO_EVENT_ID = "e_jazz_alchemia"
SIGNAL_LABELS = {
    "tags": "tagi (IDF)",
    "co_attendance": "wspólne eventy",
    "event_fit": "pasuje do eventu",
    "status": "status",
}

st.set_page_config(page_title="M4 sandbox", layout="wide")
storage = get_storage()

users = {u.id: u for u in storage.list_users()}
events = {e.id: e for e in storage.list_events()}
user_ids, event_ids = list(users), list(events)
user = users[st.sidebar.selectbox(
    "Użytkownik", user_ids, format_func=lambda uid: users[uid].name, key="m4_user",
    index=user_ids.index(DEMO_USER_ID) if DEMO_USER_ID in users else 0,
)]
event_id = st.sidebar.selectbox(
    "Wydarzenie", event_ids, format_func=lambda eid: events[eid].title, key="m4_event",
    index=event_ids.index(DEMO_EVENT_ID) if DEMO_EVENT_ID in events else 0,
)
st.sidebar.write("Tagi:", ", ".join(user.tags))
st.sidebar.write("Tagi eventu:", ", ".join(events[event_id].tags) or "—")

st.sidebar.markdown("### Wagi")
weights = {
    name: st.sidebar.slider(SIGNAL_LABELS.get(name, name), 0.0, 1.0, float(default), 0.05, key=f"m4_w_{name}")
    for name, default in WEIGHTS.items()
}
st.sidebar.caption("Domyślne: " + ", ".join(f"{k}={v:.2f}" for k, v in WEIGHTS.items()))

default_rank = {b.user.id: i for i, b in enumerate(match_breakdown(storage, user, event_id), start=1)}

col_matches, col_recs = st.columns(2)
with col_matches:
    st.subheader(f"Dopasowania: {events[event_id].title}")
    rows = []
    for place, b in enumerate(match_breakdown(storage, user, event_id, weights=weights), start=1):
        row = {"miejsce": place, "miejsce przy WEIGHTS": default_rank[b.user.id],
               "osoba": b.user.name, "score": b.score}
        row |= {label: round(b.signals[name], 3) if name in b.signals else None
                for name, label in SIGNAL_LABELS.items()}
        row |= {"wspólne tagi": ", ".join(b.shared_tags), "wspólne eventy (n)": len(b.co_event_ids),
                "status": b.status.value, "powód": match_reason(b)}
        rows.append(row)
    st.dataframe(rows, width="stretch", hide_index=True)
with col_recs:
    st.subheader("Rekomendacje")
    st.dataframe(
        [{"event": r.event.title, "score": r.score, "powód": r.reason}
         for r in recommend_events(storage, user, limit=10)],
        width="stretch",
    )
