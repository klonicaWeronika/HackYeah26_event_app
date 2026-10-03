"""M4-02 — dodatkowe sygnały: współobecność, dopasowanie do eventu, status; nadpisywanie wag."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from m4_matching.engine import (
    CO_ATTENDANCE_SATURATION,
    WEIGHTS,
    match_breakdown,
    match_for_event,
    weighted_score,
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


def _by_id(store: Storage, me: User, event_id: str) -> dict:
    return {b.user.id: b for b in match_breakdown(store, me, event_id)}


# --- mocki: złoty przypadek demo ----------------------------------------- #

def test_default_weights_put_bartek_and_natalia_on_top(storage: Storage, demo_user: User):
    ranking = [m.user.id for m in match_for_event(storage, demo_user, JAZZ)]
    assert ranking == ["u_bartek", "u_natalia", "u_kuba", "u_tomek"]


def test_breakdown_signals_on_demo_event(storage: Storage, demo_user: User):
    by_id = _by_id(storage, demo_user, JAZZ)
    bartek, natalia, kuba, tomek = (by_id[u] for u in ("u_bartek", "u_natalia", "u_kuba", "u_tomek"))

    assert bartek.co_event_ids == ("e_foto_nocna", "e_fotospacer", "e_mocak_wystawa", "e_opera_carmen")
    assert bartek.signals["co_attendance"] == 1.0                     # 4 ≥ 3 → nasycenie
    assert bartek.event_fit_tags == ("jazz",) and bartek.signals["event_fit"] == 1.0
    assert natalia.signals["event_fit"] == 0.0 and natalia.signals["co_attendance"] == 1.0
    assert kuba.co_event_ids == ("e_planszowki", "e_rejs_kino")
    assert tomek.co_event_ids == ("e_rejs_kino",)
    assert tomek.signals["co_attendance"] == pytest.approx(1 / CO_ATTENDANCE_SATURATION)
    for b in by_id.values():
        assert b.status is AttendanceStatus.GOING and b.signals["status"] == 1.0
        assert b.score == round(weighted_score(b.signals), 3)
        assert JAZZ not in b.co_event_ids                             # bieżący event się nie liczy


# --- status -------------------------------------------------------------- #

def test_going_ranks_above_interested(empty_storage: Storage):
    store = empty_storage
    event = _event(store, "e_t", ["jazz"])
    me = _user(store, "u_me", "Ja", ["jazz", "kino"])
    _user(store, "u_a", "Ada", ["jazz"])                              # alfabetycznie pierwsza…
    _user(store, "u_b", "Bogdan", ["jazz"])
    store.join_event("u_a", event, status=AttendanceStatus.INTERESTED)
    store.join_event("u_b", event, status=AttendanceStatus.GOING)

    matches = match_breakdown(store, me, event)
    assert [b.user.id for b in matches] == ["u_b", "u_a"]              # …ale GOING wygrywa
    assert matches[0].signals["status"] == 1.0 and matches[1].signals["status"] == 0.5
    expected_gap = WEIGHTS["status"] * 0.5 / sum(WEIGHTS.values())
    assert matches[0].score - matches[1].score == pytest.approx(expected_gap, abs=1e-3)


# --- współobecność ------------------------------------------------------- #

def test_co_attendance_counts_only_events_where_both_are_visible(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz"])
    _user(store, "u_o", "Ona", ["jazz"])
    now_event = _event(store, "e_now")
    for eid, days in [("e_both", 2), ("e_past", -3), ("e_hidden_other", 3), ("e_hidden_me", 4),
                      ("e_only_other", 5)]:
        _event(store, eid, days=days)
    for uid in ("u_me", "u_o"):
        store.join_event(uid, now_event)
        store.join_event(uid, "e_both")
        store.join_event(uid, "e_past")                               # przeszłe też się liczą
    store.join_event("u_me", "e_hidden_other")
    store.join_event("u_o", "e_hidden_other", open_to_meet=False)
    store.join_event("u_me", "e_hidden_me", open_to_meet=False)
    store.join_event("u_o", "e_hidden_me")
    store.join_event("u_o", "e_only_other")

    mine = _by_id(store, me, now_event)["u_o"]
    assert mine.co_event_ids == ("e_both", "e_past")
    theirs = _by_id(store, store.get_user("u_o"), now_event)["u_me"]
    assert theirs.co_event_ids == mine.co_event_ids                   # symetria A→B == B→A


def test_co_attendance_saturates(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz"])
    _user(store, "u_o", "Ona", ["jazz"])
    current = _event(store, "e_current")
    store.join_event("u_o", current)
    for n in range(6):
        signal = _by_id(store, me, current)["u_o"].signals["co_attendance"]
        assert signal == pytest.approx(min(n / CO_ATTENDANCE_SATURATION, 1.0))
        extra = _event(store, f"e_{n}", days=n + 2)
        store.join_event("u_me", extra)
        store.join_event("u_o", extra)


# --- dopasowanie do eventu ----------------------------------------------- #

def test_event_fit_is_share_of_event_tags_and_absent_without_tags(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["kino"])
    _user(store, "u_o", "Ona", ["jazz", "rock"])
    tagged = _event(store, "e_tagged", ["jazz", "opera"])
    untagged = _event(store, "e_untagged")
    for eid in (tagged, untagged):
        store.join_event("u_o", eid)

    fit = _by_id(store, me, tagged)["u_o"]
    assert fit.signals["event_fit"] == 0.5 and fit.event_fit_tags == ("jazz",)
    no_tags = _by_id(store, me, untagged)["u_o"]
    assert "event_fit" not in no_tags.signals                         # brak sygnału, nie 0
    assert no_tags.score == round(weighted_score(no_tags.signals), 3)


# --- wagi ---------------------------------------------------------------- #

def test_weights_override_changes_ranking(storage: Storage, demo_user: User):
    before = dict(WEIGHTS)

    def ranking(weights=None):
        return [m.user.id for m in match_for_event(storage, demo_user, JAZZ, weights=weights)]

    assert ranking()[0] == "u_bartek"
    assert ranking({"tags": 1.0})[0] == "u_natalia"                   # najrzadsze wspólne tagi
    assert set(ranking({"event_fit": 1.0})[:2]) == {"u_bartek", "u_kuba"}   # obaj lubią jazz
    assert ranking({"co_attendance": 1.0})[-1] == "u_tomek"           # tylko 1 wspólny event
    assert WEIGHTS == before                                          # nadpisanie nie mutuje WEIGHTS


# --- gwarancje §3.2 dla wszystkich par osoba × event --------------------- #

def test_guarantees_hold_for_every_user_and_event(storage: Storage):
    for user in storage.list_users():
        for event in storage.list_events():
            hidden = {a.user_id for a in storage.list_attendees(event.id) if not a.open_to_meet}
            matches = match_for_event(storage, user, event.id, limit=100)
            scores = [m.score for m in matches]
            assert scores == sorted(scores, reverse=True)
            assert all(0.0 <= s <= 1.0 for s in scores)
            ids = {m.user.id for m in matches}
            assert user.id not in ids and not ids & hidden
            assert all(m.reason and m.event_id == event.id for m in matches)
