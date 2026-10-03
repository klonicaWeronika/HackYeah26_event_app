"""M4-05 — rekomendacje v2: tagi + podobne osoby, kara za termin, różnorodność kategorii."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

import pytest

from m4_matching.engine import (
    REASON_MAX_LEN,
    REC_MAX_PER_CATEGORY,
    REC_TIME_HORIZON_DAYS,
    REC_TIME_PENALTY,
    REC_WEIGHTS,
    recommend_breakdown,
    recommend_events,
)
from shared.models import Category, Event, User
from shared.storage import Storage

NOW = datetime(2026, 10, 3, 12, 0)


def _event(store: Storage, event_id: str, tags: list[str] | None = None, *, days: float = 1,
           category: Category = Category.OTHER) -> str:
    start = NOW + timedelta(days=days)
    store.upsert_event(Event(id=event_id, title=event_id, tags=tags or [], start=start,
                             end=start + timedelta(hours=2), category=category,
                             venue="X", lat=50.06, lon=19.93))
    return event_id


def _user(store: Storage, user_id: str, name: str, tags: list[str]) -> User:
    return store.upsert_user(User(id=user_id, name=name, tags=tags))


def _recs(store: Storage, user: User, **kwargs) -> list[str]:
    return [r.event.id for r in recommend_events(store, user, now=NOW, **kwargs)]


# --- kandydaci ----------------------------------------------------------- #

def test_skips_past_joined_and_unrelated_events(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz"])
    _event(store, "e_ok", ["jazz"])
    _event(store, "e_past", ["jazz"], days=-2)
    _event(store, "e_joined", ["jazz"])
    _event(store, "e_unrelated", ["opera"])
    _event(store, "e_running", ["jazz"], days=-1 / 24)                # zaczął się godzinę temu, trwa
    store.join_event("u_me", "e_joined")
    assert set(_recs(store, me)) == {"e_ok", "e_running"}


def test_similar_person_going_makes_event_a_candidate(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz", "kino"])
    _user(store, "u_sim", "Bartek", ["jazz", "rock"])
    _user(store, "u_far", "Obcy", ["opera"])
    event = _event(store, "e_x", ["planszówki"])                      # tagami nie pasuje
    lonely = _event(store, "e_y", ["planszówki"])
    store.join_event("u_sim", event)
    store.join_event("u_far", lonely)                                 # 0 wspólnych tagów → nie „podobny”

    recs = recommend_events(store, me, now=NOW)
    assert [r.event.id for r in recs] == [event]
    assert recs[0].reason == "Idzie Bartek"


def test_hidden_attendee_neither_counts_nor_leaks(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz"])
    _user(store, "u_hid", "Ukryta", ["jazz"])
    event = _event(store, "e_x", ["planszówki"])
    store.join_event("u_hid", event, open_to_meet=False)
    assert recommend_events(store, me, now=NOW) == []


def test_user_without_tags_gets_nothing(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", [])
    _user(store, "u_o", "Ona", ["jazz"])
    store.join_event("u_o", _event(store, "e_x", ["jazz"]))
    assert recommend_events(store, me, now=NOW) == []


# --- sygnały i kara za termin ------------------------------------------- #

def test_social_signal_raises_score(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz", "kino"])
    _user(store, "u_sim", "Bartek", ["jazz", "kino"])
    _event(store, "e_alone", ["jazz"])
    crowd = _event(store, "e_crowd", ["jazz"])
    store.join_event("u_sim", crowd)
    assert _recs(store, me) == ["e_crowd", "e_alone"]


@pytest.mark.parametrize(("days", "factor"), [
    (0, 1.0), (REC_TIME_HORIZON_DAYS / 2, 1 - REC_TIME_PENALTY / 2),
    (REC_TIME_HORIZON_DAYS, 1 - REC_TIME_PENALTY), (REC_TIME_HORIZON_DAYS * 3, 1 - REC_TIME_PENALTY),
])
def test_time_penalty_is_linear_and_capped(empty_storage: Storage, days: float, factor: float):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz"])
    _event(store, "e_x", ["jazz"], days=days)
    (r,) = recommend_breakdown(store, me, now=NOW)
    assert r.time_factor == pytest.approx(factor)
    assert r.signals == {"tags": 1.0, "social": 0.0}                 # nikt nie idzie = prawdziwe 0
    assert r.score == pytest.approx(REC_WEIGHTS["tags"] / sum(REC_WEIGHTS.values()) * factor, abs=1e-3)


def test_nearer_event_wins_tie(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz"])
    _event(store, "e_far", ["jazz"], days=10)
    _event(store, "e_near", ["jazz"], days=1)
    assert _recs(store, me) == ["e_near", "e_far"]


def test_weights_override(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz", "kino"])
    _user(store, "u_sim", "Bartek", ["jazz", "kino"])
    _event(store, "e_tags", ["jazz"])                                 # pełne pokrycie tagów, nikt nie idzie
    social = _event(store, "e_social", ["jazz", "opera", "rock"])     # 1/3 tagów, ale idzie Bartek
    store.join_event("u_sim", social)
    assert _recs(store, me, weights={"tags": 1.0})[0] == "e_tags"
    assert _recs(store, me, weights={"social": 1.0})[0] == "e_social"


# --- różnorodność -------------------------------------------------------- #

def test_at_most_two_per_category_when_alternatives_exist(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz", "kino"])
    for i in range(4):                                                # 4 idealne koncerty…
        _event(store, f"e_music_{i}", ["jazz"], days=1 + i * 0.1, category=Category.MUSIC)
    for i, cat in enumerate([Category.CINEMA, Category.THEATRE, Category.EXHIBITION]):
        _event(store, f"e_alt_{i}", ["kino", "rock"], days=2, category=cat)   # …i słabsze alternatywy

    recs = recommend_events(store, me, now=NOW)
    counts = Counter(r.event.category for r in recs)
    assert len(recs) == 5 and max(counts.values()) == REC_MAX_PER_CATEGORY
    assert counts[Category.MUSIC] == REC_MAX_PER_CATEGORY             # 2 koncerty + 3 alternatywy
    assert [r.event.id for r in recs[:2]] == ["e_music_0", "e_music_1"]


def test_category_cap_counts_fill_ins_last(empty_storage: Storage):
    """Gdy alternatyw brakuje, pominięty koncert wraca — ale na koniec listy."""
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz", "kino"])
    for i in range(4):
        _event(store, f"e_music_{i}", ["jazz"], days=1 + i * 0.1, category=Category.MUSIC)
    for i in range(3):
        _event(store, f"e_cinema_{i}", ["kino", "rock"], days=2, category=Category.CINEMA)
    assert _recs(store, me) == ["e_music_0", "e_music_1", "e_cinema_0", "e_cinema_1", "e_music_2"]


def test_fills_with_repeated_category_when_nothing_else(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz"])
    for i in range(4):
        _event(store, f"e_music_{i}", ["jazz"], days=1 + i, category=Category.MUSIC)
    assert _recs(store, me) == [f"e_music_{i}" for i in range(4)]


@pytest.mark.parametrize("limit", [0, 1, 3])
def test_limit(storage: Storage, demo_user: User, limit: int):
    assert len(recommend_events(storage, demo_user, limit=limit, now=NOW)) == limit


# --- uzasadnienia -------------------------------------------------------- #

def test_reason_combines_tags_and_people(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["jazz", "kino"])
    event = _event(store, "e_x", ["jazz", "opera"])
    for uid, name in [("u_a", "Ada"), ("u_b", "Bogdan"), ("u_c", "Cezary"), ("u_d", "Dorota")]:
        _user(store, uid, name, ["jazz"])
        store.join_event(uid, event)
    (rec,) = recommend_events(store, me, now=NOW)
    assert rec.reason == "Pasuje do: jazz · Idą Ada, Bogdan i 2 inne osoby"


def test_reason_falls_back_to_head_count_for_long_names(empty_storage: Storage):
    store = empty_storage
    me = _user(store, "u_me", "Ja", ["sztuka współczesna", "fotografia"])
    event = _event(store, "e_x", ["sztuka współczesna", "fotografia"])
    for i in range(5):
        _user(store, f"u_{i}", f"Maksymilianna-{i} Długonazwiskowa", ["fotografia"])
        store.join_event(f"u_{i}", event)
    (rec,) = recommend_events(store, me, now=NOW)
    # imiona się nie mieszczą → liczba osób; drugi tag odpada, żeby zmieścić się w limicie
    assert rec.reason == "Pasuje do: sztuka współczesna · Idzie 5 podobnych osób"
    assert len(rec.reason) <= REASON_MAX_LEN


# --- persony demo -------------------------------------------------------- #

@pytest.mark.parametrize("user_id", ["u_ola", "u_kuba", "u_natalia"])
def test_demo_personas_get_sensible_diverse_recommendations(storage: Storage, user_id: str):
    user = storage.get_user(user_id)
    joined = {a.event_id for a in storage.list_user_attendance(user_id)}
    now = datetime.now()
    recs = recommend_events(storage, user, now=now)

    assert len(recs) == 5
    assert all(r.event.id not in joined and r.event.end_or_start >= now for r in recs)
    assert max(Counter(r.event.category for r in recs).values()) <= REC_MAX_PER_CATEGORY
    assert all(r.reason and len(r.reason) <= REASON_MAX_LEN for r in recs)
    top = recs[0]                                                     # na górze: pasuje tagami I ktoś idzie
    assert set(top.event.tags) & set(user.tags) and "Id" in top.reason


def test_demo_step5_adding_opera_changes_recommendations(storage: Storage, demo_user: User):
    """Ola dopisuje „opera” → bardziej podobna do Ani, więc eventy Ani awansują."""
    before = _recs(storage, demo_user)
    after = _recs(storage, storage.upsert_user(
        demo_user.model_copy(update={"tags": [*demo_user.tags, "opera"]})))
    assert before != after
    assert "e_nowa_huta" in after and "e_nowa_huta" not in before    # idą Ania i Bartek
