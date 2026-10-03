"""M3-06 — profile_overlap: wspólne zainteresowania i wspólne PRZYSZŁE wydarzenia, prywatność."""

from __future__ import annotations

import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from m3_profile.profile_data import profile_overlap
from shared.models import Event, User, now
from shared.storage import Storage

ROOT = Path(__file__).resolve().parents[2]


def _event(storage: Storage, eid: str, start_in: timedelta, length: timedelta | None = None) -> Event:
    start = now() + start_in
    event = Event(id=eid, title=eid, start=start, end=start + length if length else None,
                  venue="X", lat=50.06, lon=19.94)
    storage.upsert_event(event)
    return event


def _users(storage: Storage) -> tuple[User, User]:
    me = storage.upsert_user(User(id="u_me", name="Ja", tags=["jazz", "kino", "kawa"]))
    other = storage.upsert_user(User(id="u_ty", name="Ty", tags=["wino", "kino", "jazz", "joga"]))
    return me, other


def test_shared_tags_first_in_profile_order(empty_storage: Storage):
    me, other = _users(empty_storage)
    o = profile_overlap(empty_storage, me, other)
    assert o.shared_tags == ["kino", "jazz"] and o.other_tags == ["wino", "joga"]


def test_common_and_other_events_only_upcoming_sorted(empty_storage: Storage):
    me, other = _users(empty_storage)
    _event(empty_storage, "e_past", -timedelta(days=2))
    _event(empty_storage, "e_ongoing", -timedelta(days=1), length=timedelta(days=5))   # wystawa: trwa
    _event(empty_storage, "e_later", timedelta(days=3))
    _event(empty_storage, "e_soon", timedelta(hours=5))
    for eid in ("e_past", "e_ongoing", "e_later", "e_soon"):
        empty_storage.join_event(other.id, eid)
    for eid in ("e_past", "e_later"):
        empty_storage.join_event(me.id, eid)

    o = profile_overlap(empty_storage, me, other)
    assert [e.id for e in o.common_events] == ["e_later"]                  # e_past pominięty
    assert [e.id for e in o.other_events] == ["e_ongoing", "e_soon"]       # rosnąco po dacie


def test_hidden_attendance_is_not_shown_to_others(empty_storage: Storage):
    me, other = _users(empty_storage)
    _event(empty_storage, "e_secret", timedelta(days=1))
    empty_storage.join_event(other.id, "e_secret", open_to_meet=False)
    empty_storage.join_event(me.id, "e_secret")
    o = profile_overlap(empty_storage, me, other)
    assert not o.common_events and not o.other_events


def test_own_profile_shows_all_upcoming_and_marks_hidden(empty_storage: Storage):
    me, _ = _users(empty_storage)
    _event(empty_storage, "e_a", timedelta(days=1))
    _event(empty_storage, "e_b", timedelta(days=2))
    empty_storage.join_event(me.id, "e_a")
    empty_storage.join_event(me.id, "e_b", open_to_meet=False)
    o = profile_overlap(empty_storage, me, me)
    assert o.shared_tags == [] and o.other_tags == me.tags                # nie „wspólne z samym sobą”
    assert [e.id for e in o.other_events] == ["e_a", "e_b"] and o.hidden_event_ids == {"e_b"}


def test_anonymous_viewer_and_missing_events_do_not_crash(empty_storage: Storage):
    _, other = _users(empty_storage)
    empty_storage.join_event(other.id, "e_usuniety")                      # attendance bez eventu
    o = profile_overlap(empty_storage, None, other)
    assert o.shared_tags == [] and not o.common_events and not o.other_events


def test_mock_data_ola_and_bartek_have_common_events(storage: Storage):
    ola, bartek = storage.get_user("u_ola"), storage.get_user("u_bartek")
    o = profile_overlap(storage, ola, bartek)
    assert "jazz" in o.shared_tags and "e_jazz_alchemia" in {e.id for e in o.common_events}


def test_profile_data_module_does_not_import_streamlit():
    code = "import sys, m3_profile.profile_data; sys.exit('streamlit' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], cwd=ROOT).returncode == 0
