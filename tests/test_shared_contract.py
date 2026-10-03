"""Testy kontraktu shared/ — MUSZĄ przechodzić przed każdym merge do main."""

from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError

from shared.mock_data import KRAKOW_VENUES, build_mock_dataset
from shared.models import (
    Category,
    ChatMessage,
    Event,
    FilterCriteria,
    MatchResult,
    User,
    dm_room_id,
    event_room_id,
    is_in_krakow,
    stable_id,
)
from shared.storage import Storage


def _event(**overrides) -> Event:
    base = dict(id="e_test", title="Test", start=datetime(2026, 10, 10, 19), venue="X", lat=50.06, lon=19.93)
    return Event(**{**base, **overrides})


# --- modele -------------------------------------------------------------- #

def test_models_are_frozen_and_copy_with_validates():
    user = User(id="u1", name="Ala", tags=["Jazz"])
    with pytest.raises(ValidationError):
        user.name = "Ola"
    changed = user.copy_with(tags=[" #KINO ", "kino"])
    assert changed.tags == ["kino"] and user.tags == ["jazz"]


def test_match_result_score_is_bounded():
    with pytest.raises(ValidationError):
        MatchResult(user=User(id="u", name="X"), score=1.5)


def test_room_ids():
    assert event_room_id("e1") == "event:e1"
    assert dm_room_id("u_b", "u_a") == dm_room_id("u_a", "u_b") == "dm:u_a:u_b"


def test_stable_id_is_deterministic():
    assert stable_id("ev", "karnet", "url") == stable_id("ev", "karnet", "url")
    assert stable_id("ev", "karnet", "url") != stable_id("ev", "karnet", "url2")


# --- filtry -------------------------------------------------------------- #

def test_filter_categories_tags_free_and_query():
    event = _event(category=Category.MUSIC, tags=["jazz"], price_pln=0, venue="Kraków Alchemia")
    assert FilterCriteria().matches(event)
    assert FilterCriteria(categories=[Category.MUSIC]).matches(event)
    assert not FilterCriteria(categories=[Category.SPORT]).matches(event)
    assert FilterCriteria(tags=["JAZZ", "rock"]).matches(event)
    assert FilterCriteria(free_only=True).matches(event)
    assert FilterCriteria(query="krakow alchemia").matches(event)   # bez polskich znaków


def test_filter_date_range_overlaps_multi_day_events():
    exhibition = _event(start=datetime(2026, 10, 1, 10), end=datetime(2026, 10, 30, 18))
    assert FilterCriteria(date_from=date(2026, 10, 10), date_to=date(2026, 10, 12)).matches(exhibition)
    assert not FilterCriteria(date_from=date(2026, 11, 1)).matches(exhibition)
    assert not FilterCriteria(date_to=date(2026, 9, 30)).matches(exhibition)


# --- mocki --------------------------------------------------------------- #

def test_mock_dataset_is_consistent():
    ds = build_mock_dataset()
    event_ids = {e.id for e in ds.events}
    user_ids = {u.id for u in ds.users}
    assert len(ds.events) >= 30 and len(ds.users) >= 10
    assert all(is_in_krakow(e.lat, e.lon) for e in ds.events)
    assert all(is_in_krakow(v.lat, v.lon) for v in KRAKOW_VENUES.values())
    assert all(a.event_id in event_ids and a.user_id in user_ids for a in ds.attendance)
    assert any(e.start.date() == date.today() for e in ds.events), "demo potrzebuje eventów 'dziś'"


# --- storage ------------------------------------------------------------- #

def test_storage_seeds_and_filters(storage: Storage):
    assert storage.stats()["events"] == len(build_mock_dataset().events)
    music = storage.list_events(FilterCriteria(categories=[Category.MUSIC]))
    assert music and all(e.category is Category.MUSIC for e in music)
    starts = [e.start for e in storage.list_events()]
    assert starts == sorted(starts)


def test_storage_crud_invalidates_cache(storage: Storage):
    event = _event(id="e_new", title="Nowy")
    storage.upsert_event(event)
    assert storage.get_event("e_new") == event
    storage.upsert_event(event.copy_with(title="Zmieniony"))
    assert storage.get_event("e_new").title == "Zmieniony"
    assert storage.delete_event("e_new") and storage.get_event("e_new") is None


def test_attendance_join_leave(storage: Storage):
    before = len(storage.list_attendees("e_joga_jordana"))
    storage.join_event("u_ola", "e_joga_jordana")
    storage.join_event("u_ola", "e_joga_jordana")             # idempotentne
    assert len(storage.list_attendees("e_joga_jordana")) == before + 1
    assert storage.leave_event("u_ola", "e_joga_jordana")
    assert len(storage.list_attendees("e_joga_jordana")) == before


def test_chat_order_and_since(storage: Storage):
    room = event_room_id("e_joga_jordana")
    first = storage.post_message(room, "u_julia", "pierwsza")
    storage.add_message(ChatMessage(room_id=room, user_id="u_piotr", text="druga",
                                    created_at=first.created_at + timedelta(seconds=1)))
    assert [m.text for m in storage.list_messages(room)] == ["pierwsza", "druga"]
    assert [m.text for m in storage.list_messages(room, since=first.created_at)] == ["druga"]


def test_cache_sees_writes_from_another_process(tmp_path):
    """Scraper (inne połączenie / proces) zapisuje -> aplikacja widzi zmianę bez restartu."""
    db = tmp_path / "shared.db"
    app_store = Storage(db)
    assert app_store.get_event("e_external") is None             # zapełnia cache
    scraper_store = Storage(db, seed_if_empty=False)
    scraper_store.upsert_event(_event(id="e_external"))
    assert app_store.get_event("e_external") is not None
    app_store.close()
    scraper_store.close()
