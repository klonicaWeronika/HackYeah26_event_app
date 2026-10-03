"""M3-08 (wariant „tylko M3”) — zbiorczo ukryj / pokaż w dopasowaniach."""

from __future__ import annotations

import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from m3_profile.privacy import set_visibility_everywhere, visibility_summary
from m3_profile.profile_data import profile_overlap
from m4_matching.engine import match_for_event
from shared.models import AttendanceStatus, Event, now
from shared.storage import Storage

ROOT = Path(__file__).resolve().parents[2]
OLA = "u_ola"


def _visible_in_matches(storage: Storage, user_id: str) -> set[str]:
    """Wydarzenia, na których `user_id` pojawia się w dopasowaniach u kogokolwiek innego (M4)."""
    found = set()
    for att in storage.list_user_attendance(user_id):
        for other in storage.list_attendees(att.event_id):
            viewer = storage.get_user(other.user_id)
            if other.user_id != user_id and viewer and any(
                m.user.id == user_id for m in match_for_event(storage, viewer, att.event_id)
            ):
                found.add(att.event_id)
    return found


def test_hidden_person_disappears_from_all_matches_and_comes_back(storage: Storage):
    """DoD M3-08: ukryta osoba nie pojawia się w match_for_event (M4) — bez zmian w M4."""
    assert _visible_in_matches(storage, OLA)                              # przed: widoczna
    changed = set_visibility_everywhere(storage, OLA, False)
    assert changed == len(storage.list_user_attendance(OLA))
    assert _visible_in_matches(storage, OLA) == set()
    set_visibility_everywhere(storage, OLA, True)
    assert _visible_in_matches(storage, OLA)


def test_bulk_change_keeps_status_and_signup_date_and_is_idempotent(storage: Storage):
    storage.join_event(OLA, "e_joga_jordana", status=AttendanceStatus.INTERESTED)
    before = {a.event_id: (a.status, a.created_at) for a in storage.list_user_attendance(OLA)}
    set_visibility_everywhere(storage, OLA, False)
    after = {a.event_id: (a.status, a.created_at) for a in storage.list_user_attendance(OLA)}
    assert after == before
    assert set_visibility_everywhere(storage, OLA, False) == 0


def test_hidden_person_shows_no_events_on_profile_for_others(storage: Storage):
    set_visibility_everywhere(storage, OLA, False)
    o = profile_overlap(storage, storage.get_user("u_bartek"), storage.get_user(OLA))
    assert not o.common_events and not o.other_events


def test_summary_counts_only_upcoming_events(empty_storage: Storage):
    from shared.models import User

    empty_storage.upsert_user(User(id="u_x", name="X"))
    plan = {"e_past": -timedelta(days=2), "e_next": timedelta(days=1), "e_later": timedelta(days=5)}
    for eid, delta in plan.items():
        event = Event(id=eid, title=eid, start=now() + delta, venue="V", lat=50.06, lon=19.94)
        empty_storage.upsert_event(event)
        empty_storage.join_event("u_x", eid)
    empty_storage.join_event("u_x", "e_later", open_to_meet=False)
    summary = visibility_summary(empty_storage, "u_x")
    assert (summary.visible, summary.total, summary.hidden) == (1, 2, 1)


def test_privacy_module_does_not_import_streamlit():
    code = "import sys, m3_profile.privacy; sys.exit('streamlit' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], cwd=ROOT).returncode == 0
