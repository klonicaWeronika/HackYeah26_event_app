"""Przykładowa społeczność na prawdziwych eventach (shared/example_data.py).

Eventy „ze scrapera” budujemy względem dziś — test nie zależy od dat w data/seed_events.json.
"""

from datetime import date, datetime, time, timedelta

import pytest

from shared.example_data import build_example_dataset, community_users
from shared.mock_data import DEMO_USER_ID
from shared.models import Category, Event
from shared.storage import Storage

_TAGS = [["jazz", "klasyka"], ["teatr", "literatura"], ["opera"], ["kino", "fotografia"], ["dla dzieci", "teatr"],
         ["technologia", "startupy"], ["rock", "pop"], ["hip-hop"], ["sztuka współczesna", "design"], []]
_CATEGORIES = [Category.MUSIC, Category.THEATRE, Category.MUSIC, Category.CINEMA, Category.THEATRE,
               Category.MEETUP, Category.MUSIC, Category.MUSIC, Category.EXHIBITION, Category.OTHER]


def _scraped_events(n: int = 80) -> list[Event]:
    today = date.today()
    return [
        Event(id=f"ev_test_{i:03d}", title=f"Wydarzenie {i}", category=_CATEGORIES[i % 10], tags=_TAGS[i % 10],
              start=datetime.combine(today + timedelta(days=i % 25), time(18 + i % 3, 0)),
              venue="Miejsce", lat=50.06, lon=19.94, source="scraper:karnet")
        for i in range(n)
    ]


@pytest.fixture
def example_storage(storage: Storage) -> Storage:
    storage.upsert_events(_scraped_events())
    storage.seed_example_data()
    return storage


def test_dataset_is_consistent_and_deterministic(storage: Storage):
    events = storage.list_events() + _scraped_events()
    now = datetime.now().replace(microsecond=0)
    ds = build_example_dataset(events, storage.list_users(), reference_now=now)
    again = build_example_dataset(events, storage.list_users(), reference_now=now)
    assert ds.attendance == again.attendance and ds.messages == again.messages

    event_ids = {e.id for e in events if e.source.startswith("scraper:")}
    user_ids = {u.id for u in storage.list_users()} | {u.id for u in ds.users}
    assert ds.users and ds.attendance and ds.messages
    assert all(a.event_id in event_ids for a in ds.attendance), "tylko eventy ze scrapera, mocki bez zmian"
    assert all(a.user_id in user_ids for a in ds.attendance)
    assert all(m.user_id in user_ids and m.created_at <= now for m in ds.messages)
    assert len({m.id for m in ds.messages}) == len(ds.messages)
    assert any(m.room_id.startswith("event:") for m in ds.messages)
    assert any(m.room_id.startswith("dm:") and DEMO_USER_ID in m.room_id for m in ds.messages)


def test_community_does_not_collide_with_personas(storage: Storage):
    assert not {u.id for u in community_users()} & {u.id for u in storage.list_users()}


def test_personas_never_meet_on_real_events(example_storage: Storage):
    """Nowe wspólne wydarzenia między personami zmieniłyby ranking w scenariuszu demo."""
    personas = {u.id for u in example_storage.list_users()} - {u.id for u in community_users()}
    for event in _scraped_events():
        going = {a.user_id for a in example_storage.list_attendees(event.id)}
        assert len(going & personas) <= 1, event.id


def test_demo_scenario_survives_example_data(example_storage: Storage):
    from m4_matching.engine import match_for_event

    ola = example_storage.get_user(DEMO_USER_ID)
    ranking = [m.user.id for m in match_for_event(example_storage, ola, "e_jazz_alchemia", limit=20)]
    assert set(ranking[:2]) == {"u_bartek", "u_natalia"}


def test_seed_is_idempotent(example_storage: Storage):
    before = example_storage.stats()
    example_storage.seed_example_data()
    assert example_storage.stats() == before


def test_hottest_events_get_a_crowd(example_storage: Storage):
    """Na screeny: CROWD_EVENTS najgorętszych eventów ma kilkadziesiąt zapisanych (tylko społeczność)."""
    from shared.example_data import CROWD_EVENTS, CROWD_SIZES

    community = {u.id for u in community_users()}
    sizes = sorted((len(example_storage.list_attendees(e.id)) for e in _scraped_events()), reverse=True)
    assert all(n >= CROWD_SIZES[1] for n in sizes[:CROWD_EVENTS]), sizes[:CROWD_EVENTS]
    assert sizes[0] >= CROWD_SIZES[0]
    crowded = max(_scraped_events(), key=lambda e: len(example_storage.list_attendees(e.id)))
    going = {a.user_id for a in example_storage.list_attendees(crowded.id)}
    assert len(going - community) <= 1                                # persony nie robią tłumu


def test_community_profiles_are_valid_and_unique():
    """Te same zasady co walidacja profilu M3: 3–10 tagów, bio ≤ 280; unikalne ID i zdjęcia."""
    users = community_users()
    assert len({u.id for u in users}) == len(users)
    assert len({u.avatar_url for u in users}) == len(users)
    assert all(3 <= len(u.tags) <= 10 and len(u.bio) <= 280 and u.name for u in users)
