"""M4-09 — widget „Polecane dla Ciebie”: mini-karty, „idzie N osób, w tym X pasujących”."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from m4_matching.engine import attendance_summary, recommend_events, recommend_top
from m4_matching.widgets import MAX_AVATARS, people_html
from shared.models import User
from shared.storage import Storage


@pytest.mark.parametrize(("total", "matching", "expected"), [
    (0, 0, "Nikt się jeszcze nie zapisał"),
    (1, 0, "Idzie 1 osoba"),
    (1, 1, "Idzie 1 pasująca osoba"),
    (3, 3, "Idą 3 pasujące osoby"),
    (3, 1, "Idą 3 osoby, w tym 1 pasująca"),
    (5, 2, "Idzie 5 osób, w tym 2 pasujące"),
    (12, 5, "Idzie 12 osób, w tym 5 pasujących"),
    (22, 0, "Idą 22 osoby"),
])
def test_attendance_summary_inflection(total: int, matching: int, expected: str):
    assert attendance_summary(total, matching) == expected


def test_recommend_top_matches_recommend_events(storage: Storage, demo_user: User):
    top = recommend_top(storage, demo_user)
    recs = recommend_events(storage, demo_user)
    assert [r.event.id for r in top] == [r.event.id for r in recs]
    assert [r.score for r in top] == [r.score for r in recs]


def test_people_html_shows_faces_and_escapes_names(empty_storage: Storage):
    from datetime import datetime, timedelta

    from m4_matching.engine import RecBreakdown
    from shared.models import Event

    event = Event(id="e", title="t", start=datetime.now() + timedelta(days=1), venue="X", lat=50.0, lon=19.9)
    people = tuple(User(id=f"u{i}", name=f"<b>Osoba {i}</b>") for i in range(5))
    rec = RecBreakdown(event=event, score=0.5, signals={}, time_factor=1.0, fit_tags=(), similar_people=people)
    out = people_html(rec, total=7)
    assert out.count('title="') == MAX_AVATARS                         # max 3 twarze
    assert "<b>Osoba" not in out and "&lt;b&gt;Osoba 0" in out
    assert "Idzie 7 osób, w tym 5 pasujących" in out

    nobody = RecBreakdown(event=event, score=0.5, signals={}, time_factor=1.0, fit_tags=("jazz",),
                          similar_people=())
    assert "👥" in people_html(nobody, total=0) and "Nikt się jeszcze nie zapisał" in people_html(nobody, 0)


# --- render w AppTest ----------------------------------------------------- #

def _widget_app(user_id: str) -> None:
    from m4_matching.widgets import render_recommendations
    from shared.storage import Storage as _Storage

    store = _Storage(":memory:")
    render_recommendations(store, store.get_user(user_id))


def _run(user_id: str) -> AppTest:
    at = AppTest.from_function(_widget_app, args=(user_id,), default_timeout=30).run()
    assert not at.exception, at.exception
    return at


def test_widget_renders_five_cards_for_demo_user(storage: Storage, demo_user: User):
    at = _run("u_ola")
    expected = [r.event.title for r in recommend_events(storage, demo_user)]
    text = "\n".join(m.value for m in at.markdown)
    assert all(title in text for title in expected)
    assert [b.label for b in at.button] == ["Pokaż"] * len(expected)
    assert "w tym" in text or "pasując" in text                       # podsumowanie uczestników


def test_show_button_selects_event():
    at = _run("u_ola")
    at.button[0].click().run()
    assert not at.exception, at.exception
    assert at.session_state["selected_event_id"] == at.button[0].key.removeprefix("m4_rec_")
