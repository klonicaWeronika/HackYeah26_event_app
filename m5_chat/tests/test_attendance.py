"""M5-03 — zapis na wydarzenie: logika (service) i kontrolki (AppTest, izolowana baza w RAM)."""

import pytest
from streamlit.testing.v1 import AppTest

from m4_matching.engine import match_for_event
from m5_chat.service import attendance_counts, set_attendance
from shared.models import AttendanceStatus
from shared.storage import Storage

EVENT = "e_python_meetup"           # mocki: Ola NIE jest zapisana, Kuba jest
GOING, INTERESTED = AttendanceStatus.GOING, AttendanceStatus.INTERESTED


def _matched_ids(storage: Storage, viewer_id: str, event_id: str = EVENT) -> set[str]:
    return {m.user.id for m in match_for_event(storage, storage.get_user(viewer_id), event_id)}


# --------------------------------------------------------------------------- #
# Logika (service.py)
# --------------------------------------------------------------------------- #

def test_join_makes_me_visible_in_matches_of_others(storage: Storage):
    assert "u_ola" not in _matched_ids(storage, "u_kuba")
    att = set_attendance(storage, "u_ola", EVENT, GOING)
    assert att.status is GOING and att.open_to_meet
    assert "u_ola" in _matched_ids(storage, "u_kuba")


def test_status_change_keeps_consent_and_signup_time(storage: Storage):
    first = set_attendance(storage, "u_ola", EVENT, GOING, open_to_meet=False)
    changed = set_attendance(storage, "u_ola", EVENT, INTERESTED)
    assert changed.status is INTERESTED
    assert changed.open_to_meet is False
    assert changed.created_at == first.created_at


def test_hidden_or_left_user_disappears_from_matches(storage: Storage):
    set_attendance(storage, "u_ola", EVENT, GOING, open_to_meet=False)
    assert "u_ola" not in _matched_ids(storage, "u_kuba")
    set_attendance(storage, "u_ola", EVENT, GOING, open_to_meet=True)
    assert "u_ola" in _matched_ids(storage, "u_kuba")
    assert set_attendance(storage, "u_ola", EVENT, None) is None
    assert storage.get_attendance("u_ola", EVENT) is None
    assert "u_ola" not in _matched_ids(storage, "u_kuba")


def test_attendance_counts_by_status(storage: Storage):
    before = attendance_counts(storage, EVENT)
    set_attendance(storage, "u_ola", EVENT, INTERESTED)
    after = attendance_counts(storage, EVENT)
    assert after[INTERESTED] == before[INTERESTED] + 1
    assert after[GOING] == before[GOING]


# --------------------------------------------------------------------------- #
# Kontrolki (chat_view.render_attendance_controls)
# --------------------------------------------------------------------------- #

def _controls_app(event_id: str = "e_python_meetup"):
    from m5_chat.chat_view import render_attendance_controls
    from shared import state
    from shared.storage import get_storage

    storage = get_storage()
    state.init()   # zalogowana: u_ola (domyślna)
    render_attendance_controls(storage, storage.get_event(event_id), storage.get_user(state.current_user_id()))


@pytest.fixture
def controls(storage: Storage, monkeypatch) -> AppTest:
    monkeypatch.setattr("shared.storage._default_storage", storage)
    return AppTest.from_function(_controls_app, default_timeout=30)


def test_click_going_saves_and_shows_consent_toggle(controls: AppTest, storage: Storage):
    at = controls.run()
    assert at.segmented_control(key=f"m5_status_u_ola_{EVENT}").value is None
    assert not at.toggle                                     # niezapisana -> brak przełącznika zgody

    at.segmented_control(key=f"m5_status_u_ola_{EVENT}").set_value(GOING).run()
    assert not at.exception, at.exception
    assert storage.get_attendance("u_ola", EVENT).status is GOING
    assert "u_ola" in _matched_ids(storage, "u_kuba")      # od razu u innych
    assert at.toggle(key=f"m5_open_u_ola_{EVENT}").value is True


def test_switch_to_interested_then_deselect_leaves(controls: AppTest, storage: Storage):
    at = controls.run()
    status = f"m5_status_u_ola_{EVENT}"
    at.segmented_control(key=status).set_value(INTERESTED).run()
    assert storage.get_attendance("u_ola", EVENT).status is INTERESTED
    at.segmented_control(key=status).set_value(None).run()     # ponowny klik zaznaczonej opcji
    assert storage.get_attendance("u_ola", EVENT) is None


def test_leave_button(controls: AppTest, storage: Storage):
    set_attendance(storage, "u_ola", EVENT, GOING)
    at = controls.run()
    at.button(key=f"m5_leave_u_ola_{EVENT}").click().run()
    assert storage.get_attendance("u_ola", EVENT) is None
    assert at.segmented_control(key=f"m5_status_u_ola_{EVENT}").value is None


def test_consent_toggle_hides_me_from_matches(controls: AppTest, storage: Storage):
    set_attendance(storage, "u_ola", EVENT, GOING)
    at = controls.run()
    at.toggle(key=f"m5_open_u_ola_{EVENT}").set_value(False).run()
    assert storage.get_attendance("u_ola", EVENT).open_to_meet is False
    assert storage.get_attendance("u_ola", EVENT).status is GOING
    assert "u_ola" not in _matched_ids(storage, "u_kuba")


def test_widgets_follow_database_changes_from_other_tabs(controls: AppTest, storage: Storage):
    at = controls.run()
    set_attendance(storage, "u_ola", EVENT, INTERESTED)      # np. druga karta albo „Reset demo”
    at.run()
    assert at.segmented_control(key=f"m5_status_u_ola_{EVENT}").value is INTERESTED


def test_switching_user_does_not_leak_consent_to_other_person(storage: Storage, monkeypatch):
    monkeypatch.setattr("shared.storage._default_storage", storage)
    at = AppTest.from_function(_controls_app, kwargs={"event_id": "e_jazz_alchemia"}, default_timeout=30).run()
    at.toggle(key="m5_open_u_ola_e_jazz_alchemia").set_value(False).run()
    at.session_state["user_id"] = "u_kuba"                  # „Zaloguj jako” (M3) w tej samej karcie
    at.run()
    assert storage.get_attendance("u_kuba", "e_jazz_alchemia").open_to_meet is True
    assert at.toggle(key="m5_open_u_kuba_e_jazz_alchemia").value is True
