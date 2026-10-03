"""M4-06 — match_users: globalne dopasowania do profilu (event_id=None)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from m4_matching.engine import REASON_MAX_LEN, match_users
from shared.models import Event, User
from shared.storage import Storage


def _event(store: Storage, event_id: str, *, days: int = 1) -> str:
    start = datetime.now() + timedelta(days=days)
    store.upsert_event(Event(id=event_id, title=event_id, start=start, end=start + timedelta(hours=2),
                             venue="X", lat=50.06, lon=19.93))
    return event_id


def _user(store: Storage, user_id: str, name: str, tags: list[str]) -> User:
    return store.upsert_user(User(id=user_id, name=name, tags=tags))


def _ids(store: Storage, user: User, **kwargs) -> list[str]:
    return [m.user.id for m in match_users(store, user, **kwargs)]


# --- gwarancje §3.2 ------------------------------------------------------ #

def test_guarantees_for_every_mock_user(storage: Storage):
    for user in storage.list_users():
        matches = match_users(storage, user, limit=100)
        scores = [m.score for m in matches]
        assert matches and user.id not in {m.user.id for m in matches}
        assert scores == sorted(scores, reverse=True)
        assert all(0.0 < s <= 1.0 for s in scores)                    # zero = nic wspólnego → poza listą
        assert all(m.event_id is None for m in matches)
        assert all(m.reason and len(m.reason) <= REASON_MAX_LEN for m in matches)
        assert all("też" not in m.reason for m in matches)            # bez kontekstu bieżącego eventu


def test_score_is_symmetric(storage: Storage):
    users = storage.list_users()
    score = {(u.id, m.user.id): m.score for u in users for m in match_users(storage, u, limit=100)}
    for (a, b), value in score.items():
        assert score[(b, a)] == value


# --- złote przypadki ----------------------------------------------------- #

def test_ola_is_closest_to_natalia_and_bartek(storage: Storage, demo_user: User):
    top = match_users(storage, demo_user, limit=2)
    assert {m.user.id for m in top} == {"u_natalia", "u_bartek"}
    bartek = next(m for m in top if m.user.id == "u_bartek")
    assert bartek.shared_tags == ["jazz", "fotografia"]
    assert bartek.reason.startswith("Wspólne: jazz, fotografia · Razem na ")


def test_kuba_is_closest_to_tomek(storage: Storage):
    assert _ids(storage, storage.get_user("u_kuba"))[0] == "u_tomek"


def test_profile_edit_reranks_immediately(storage: Storage, demo_user: User):
    """DoD: zmiana tagów w profilu (M3) od razu zmienia ranking — Ola + „opera” → Ania wyżej."""
    before = _ids(storage, demo_user, limit=100)
    edited = storage.upsert_user(demo_user.model_copy(update={"tags": [*demo_user.tags, "opera"]}))
    after = _ids(storage, edited, limit=100)
    assert after.index("u_ania") < before.index("u_ania")


def test_ties_are_broken_alphabetically(storage: Storage, demo_user: User):
    matches = match_users(storage, demo_user, limit=100)
    keys = [(-m.score, m.user.name.casefold(), m.user.id) for m in matches]
    assert keys == sorted(keys)


# --- wykluczenia i współobecność ----------------------------------------- #

def test_nothing_in_common_is_excluded(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz"])
    _user(store, "u_same", "Ada", ["jazz"])
    _user(store, "u_other", "Obcy", ["opera"])
    assert _ids(store, me) == ["u_same"]


def test_co_attendance_counts_only_when_both_visible(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz"])
    _user(store, "u_o", "Obcy", ["opera"])                            # łączy nas tylko event
    event = _event(store, "e_x")
    store.join_event("u_me", event)
    store.join_event("u_o", event, open_to_meet=False)
    assert _ids(store, me) == []                                      # ukryty zapis nie wycieka

    store.join_event("u_o", event, open_to_meet=True)
    (match,) = match_users(store, me)
    assert match.user.id == "u_o" and match.reason == "Razem na 1 wydarzeniu"


def test_past_events_are_mentioned_first(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz"])
    _user(store, "u_o", "Ona", ["jazz"])
    for eid, days in [("e_past", -7), ("e_next", 3)]:
        _event(store, eid, days=days)
        for uid in ("u_me", "u_o"):
            store.join_event(uid, eid)
    (match,) = match_users(store, me)
    assert match.reason == "Wspólne: jazz · Już razem na 1 wydarzeniu"


def test_user_without_tags_and_events_gets_nothing(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Nowy", [])
    _user(store, "u_o", "Ona", ["jazz"])
    assert match_users(store, me) == []


@pytest.mark.parametrize("limit", [0, 1, 3, 10])
def test_limit_returns_prefix(storage: Storage, demo_user: User, limit: int):
    full = _ids(storage, demo_user, limit=100)
    assert _ids(storage, demo_user, limit=limit) == full[:limit]


def test_hidden_everywhere_is_excluded(empty_storage: Storage):
    """M3-08: „ukryj mnie we wszystkich dopasowaniach” = open_to_meet=False w KAŻDYM zapisie."""
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz"])
    _user(store, "u_o", "Ona", ["jazz"])
    _user(store, "u_new", "Nowy", ["jazz"])                           # bez zapisów → widoczny
    for eid in ("e_a", "e_b"):
        store.join_event("u_o", _event(store, eid), open_to_meet=False)
    assert _ids(store, me) == ["u_new"]

    store.join_event("u_o", "e_b", open_to_meet=True)                 # widoczna choć w jednym zapisie
    assert set(_ids(store, me)) == {"u_new", "u_o"}
