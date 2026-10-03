"""M4-03 — uzasadnienia PL: odmiana liczebników, limit długości, kolejność treści."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from m4_matching.engine import (
    REASON_MAX_LEN,
    events_locative,
    match_breakdown,
    match_for_event,
    match_reason,
    plural_pl,
    recommend_events,
)
from shared.models import AttendanceStatus, Event, User
from shared.storage import Storage

JAZZ = "e_jazz_alchemia"


def _event(store: Storage, event_id: str, tags: list[str] | None = None, *, days: int = 1) -> str:
    start = datetime.now() + timedelta(days=days)
    store.upsert_event(Event(id=event_id, title=event_id, tags=tags or [], start=start,
                             venue="X", lat=50.06, lon=19.93))
    return event_id


def _user(store: Storage, user_id: str, name: str, tags: list[str]) -> User:
    return store.upsert_user(User(id=user_id, name=name, tags=tags))


def _reason_for(store: Storage, me: User, event_id: str, other_id: str) -> str:
    return next(m.reason for m in match_for_event(store, me, event_id) if m.user.id == other_id)


# --- odmiana ------------------------------------------------------------- #

@pytest.mark.parametrize(("n", "expected"), [
    (1, "wydarzenie"), (2, "wydarzenia"), (4, "wydarzenia"), (5, "wydarzeń"), (0, "wydarzeń"),
    (12, "wydarzeń"), (14, "wydarzeń"), (21, "wydarzeń"), (22, "wydarzenia"), (112, "wydarzeń"),
    (124, "wydarzenia"),
])
def test_plural_pl(n: int, expected: str):
    assert plural_pl(n, "wydarzenie", "wydarzenia", "wydarzeń") == expected


@pytest.mark.parametrize(("n", "expected"), [
    (1, "1 wydarzeniu"), (2, "2 wydarzeniach"), (5, "5 wydarzeniach"), (22, "22 wydarzeniach"),
])
def test_events_locative(n: int, expected: str):
    assert events_locative(n) == expected


# --- mocki --------------------------------------------------------------- #

def test_every_mock_reason_is_nonempty_and_short(storage: Storage):
    for me in storage.list_users():
        for event in storage.list_events():
            for m in match_for_event(storage, me, event.id):
                assert m.reason.strip(), (me.id, event.id, m.user.id)
                assert len(m.reason) <= REASON_MAX_LEN, m.reason
        for r in recommend_events(storage, me):
            assert r.reason.strip() and len(r.reason) <= REASON_MAX_LEN, r.reason


def test_demo_reasons_on_jazz_event(storage: Storage, demo_user: User):
    reasons = {m.user.id: m.reason for m in match_for_event(storage, demo_user, JAZZ)}
    assert reasons["u_bartek"] == "Wspólne: jazz, fotografia · Razem też na 4 wydarzeniach"
    assert reasons["u_tomek"] == "Wspólne: kino · Razem też na 1 wydarzeniu"


def test_reason_never_uses_gendered_forms(storage: Storage):
    text = " ".join(m.reason for me in storage.list_users() for e in storage.list_events()
                    for m in match_for_event(storage, me, e.id))
    for gendered in ("Oboje", "Byliście", "Byłyście", "lubicie"):
        assert gendered not in text


# --- własne scenariusze -------------------------------------------------- #

def test_past_co_attendance_wins_over_upcoming(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz"])
    _user(store, "u_o", "Ona", ["jazz"])
    current = _event(store, "e_now")
    for eid, days in [("e_past1", -5), ("e_past2", -2), ("e_next", 3)]:
        _event(store, eid, days=days)
    for uid in ("u_me", "u_o"):
        for eid in (current, "e_past1", "e_past2", "e_next"):
            store.join_event(uid, eid)

    b = next(b for b in match_breakdown(store, me, current) if b.user.id == "u_o")
    assert b.co_past_count == 2
    assert match_reason(b) == "Wspólne: jazz · Już razem na 2 wydarzeniach"


def test_co_attendance_alone_without_shared_tags(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["kino"])
    _user(store, "u_o", "Ona", ["jazz"])
    current, other = _event(store, "e_now"), _event(store, "e_other", days=2)
    for uid in ("u_me", "u_o"):
        store.join_event(uid, other)
    store.join_event("u_o", current)
    assert _reason_for(store, me, current, "u_o") == "Razem też na 1 wydarzeniu"


def test_event_fit_when_nothing_shared(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["kino"])
    _user(store, "u_o", "Ona", ["jazz", "opera"])
    event = _event(store, "e_t", ["opera", "klasyka"])
    store.join_event("u_o", event)
    assert _reason_for(store, me, event, "u_o") == "Pasuje do wydarzenia: opera"


@pytest.mark.parametrize(("status", "expected"), [
    (AttendanceStatus.GOING, "Idziecie na to samo wydarzenie"),
    (AttendanceStatus.INTERESTED, "Też rozważa to wydarzenie"),
])
def test_status_fallback(empty_storage: Storage, status: AttendanceStatus, expected: str):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["kino"])
    _user(store, "u_o", "Ona", ["jazz"])
    event = _event(store, "e_t")
    store.join_event("u_o", event, status=status)
    assert _reason_for(store, me, event, "u_o") == expected


def test_long_tags_fit_limit_without_cutting_words_when_possible(empty_storage: Storage):
    store = empty_storage
    tags = ["sztuka współczesna", "architektura", "fotografia"]
    me = _user(store, "u_me", "Ja", tags)
    _user(store, "u_o", "Ona", tags)
    current = _event(store, "e_now")
    for n in range(3):
        extra = _event(store, f"e_{n}", days=n + 2)
        for uid in ("u_me", "u_o"):
            store.join_event(uid, extra)
    store.join_event("u_o", current)

    reason = _reason_for(store, me, current, "u_o")
    assert len(reason) <= REASON_MAX_LEN
    assert "…" not in reason                                          # całe tagi, bez ucinania
    assert reason.endswith(" · Razem też na 3 wydarzeniach")


def test_single_overlong_tag_is_truncated_with_ellipsis(empty_storage: Storage):
    store = empty_storage
    tag = "bardzo długie zainteresowanie " * 3
    me = _user(store, "u_me", "Ja", [tag])
    _user(store, "u_o", "Ona", [tag])
    event = _event(store, "e_t")
    store.join_event("u_o", event)

    reason = _reason_for(store, me, event, "u_o")
    assert reason.startswith("Wspólne: bardzo długie") and reason.endswith("…")
    assert len(reason) <= REASON_MAX_LEN
