"""M5-05 — prywatne rozmowy (DM): logika (service) i UI (AppTest, izolowana baza w RAM)."""

from datetime import datetime, timedelta

import pytest
from streamlit.testing.v1 import AppTest

from m5_chat.service import (
    can_access_room, dm_participants, escape_markdown, list_conversations, room_title, send_message,
)
from shared.config import FEATURES
from shared.models import ChatMessage, dm_room_id, event_room_id
from shared.state import View
from shared.storage import Storage

OLA_KUBA = dm_room_id("u_ola", "u_kuba")


def _post(storage: Storage, room_id: str, user_id: str, text: str, minutes_ago: int) -> ChatMessage:
    return storage.add_message(ChatMessage(
        room_id=room_id, user_id=user_id, text=text, created_at=datetime.now() - timedelta(minutes=minutes_ago),
    ))


# --------------------------------------------------------------------------- #
# Logika (service.py)
# --------------------------------------------------------------------------- #

def test_dm_participants():
    assert dm_participants(OLA_KUBA) == ("u_kuba", "u_ola")
    assert dm_participants(event_room_id("e_jazz_alchemia")) is None
    assert dm_participants("dm:u_ola") is None


def test_only_participants_can_access_and_post_to_dm(storage: Storage):
    assert can_access_room(OLA_KUBA, "u_ola") and can_access_room(OLA_KUBA, "u_kuba")
    assert not can_access_room(OLA_KUBA, "u_marta")
    assert can_access_room(event_room_id("e_jazz_alchemia"), "u_marta")
    assert send_message(storage, OLA_KUBA, "u_marta", "podglądam") is None
    assert send_message(storage, OLA_KUBA, "u_kuba", "hej") is not None
    assert [m.user_id for m in storage.list_messages(OLA_KUBA)] == ["u_kuba"]


def test_list_conversations_newest_first_and_only_mine(storage: Storage):
    _post(storage, OLA_KUBA, "u_kuba", "a", minutes_ago=30)
    _post(storage, dm_room_id("u_ola", "u_marta"), "u_ola", "b", minutes_ago=5)
    _post(storage, dm_room_id("u_kuba", "u_marta"), "u_marta", "c", minutes_ago=1)   # nie Oli
    _post(storage, event_room_id("e_jazz_alchemia"), "u_kuba", "d", minutes_ago=0)  # nie DM

    assert [(c.other.id, c.last.text) for c in list_conversations(storage, "u_ola")] == [
        ("u_marta", "b"), ("u_kuba", "a"),
    ]
    assert [c.other.id for c in list_conversations(storage, "u_kuba")] == ["u_marta", "u_ola"]
    assert list_conversations(storage, "u_bartek") == []


def test_dm_title_shows_the_other_person(storage: Storage):
    assert room_title(storage, OLA_KUBA, viewer_id="u_ola") == "💬 Kuba"
    assert room_title(storage, OLA_KUBA, viewer_id="u_kuba") == "💬 Ola"
    both = room_title(storage, OLA_KUBA)
    assert "Ola" in both and "Kuba" in both


# --------------------------------------------------------------------------- #
# UI (chat_view: render_dm_list, open_dm, render_chat_room dla DM)
# --------------------------------------------------------------------------- #

def _dm_app():
    import streamlit as st

    from m5_chat.chat_view import render_chat_room, render_dm_list
    from shared import state
    from shared.state import View
    from shared.storage import get_storage

    storage = get_storage()
    state.init()   # zalogowana: u_ola (domyślna)
    user = storage.get_user(state.current_user_id())
    with st.sidebar:
        render_dm_list(storage, user)
    if state.current_view() is View.CHAT and state.chat_room_id():
        render_chat_room(storage, user, state.chat_room_id())


@pytest.fixture
def dm_app(storage: Storage, monkeypatch) -> AppTest:
    monkeypatch.setattr("shared.storage._default_storage", storage)
    return AppTest.from_function(_dm_app, default_timeout=30)


def test_clicking_conversation_opens_private_chat(dm_app: AppTest, storage: Storage):
    _post(storage, OLA_KUBA, "u_kuba", "hej Ola, idziesz na jazz?", minutes_ago=3)
    at = dm_app.run()
    entry = at.button(key=f"m5_dm_{OLA_KUBA}")
    assert "Kuba" in entry.label and "hej Ola" in entry.label

    entry.click().run()
    assert not at.exception, at.exception
    assert at.session_state["view"] == View.CHAT
    assert at.session_state["chat_room_id"] == OLA_KUBA
    assert "### 💬 Kuba" in [m.value for m in at.markdown]
    assert any("hej Ola, idziesz na jazz?" in h.value for h in at.get("html"))


def test_conversation_label_marks_my_message_and_is_escaped(dm_app: AppTest, storage: Storage):
    _post(storage, OLA_KUBA, "u_ola", "**hej** [x](javascript:y)\ndruga linia", minutes_ago=1)
    at = dm_app.run()
    label = at.button(key=f"m5_dm_{OLA_KUBA}").label
    assert f"— {escape_markdown('Ty: **hej** [x](javascript:y)')}" in label
    assert "druga linia" not in label


def test_empty_conversation_list(dm_app: AppTest):
    at = dm_app.run()
    assert any("Brak prywatnych rozmów" in c.value for c in at.caption)


def test_someone_elses_dm_is_locked(dm_app: AppTest, storage: Storage):
    _post(storage, OLA_KUBA, "u_kuba", "tajemnica", minutes_ago=1)
    dm_app.session_state["user_id"] = "u_marta"      # np. „Zaloguj jako” z otwartym DM Oli
    dm_app.session_state["view"] = View.CHAT
    dm_app.session_state["chat_room_id"] = OLA_KUBA
    at = dm_app.run()
    assert any("prywatna rozmowa innych" in w.value for w in at.warning)
    assert not any("tajemnica" in h.value for h in at.get("html"))
    assert not at.chat_input


def _open_dm_to_self_app():
    import streamlit as st

    from m5_chat.chat_view import open_dm
    from shared import state

    state.init()
    st.button("Napisz", key="m5_t_self", on_click=open_dm, args=("u_ola", "u_ola"))


def test_open_dm_to_myself_does_nothing():
    at = AppTest.from_function(_open_dm_to_self_app, default_timeout=30).run()
    at.button(key="m5_t_self").click().run()
    assert at.session_state["view"] == View.MAP
    assert at.session_state["chat_room_id"] is None


# --------------------------------------------------------------------------- #
# Gotowy przycisk „Napisz” (DM) dla kart osób bez kontekstu wydarzenia
# --------------------------------------------------------------------------- #

def _cards_app():
    from m5_chat.chat_view import render_dm_button
    from shared import state

    state.init()   # zalogowana: u_ola
    for other in ("u_ola", "u_kuba"):   # „karta” samej siebie i Kuby
        render_dm_button(state.current_user_id(), other, key=f"m5_t_card_{other}")


def test_dm_button_for_person_cards(monkeypatch):
    monkeypatch.setitem(FEATURES, "dm_chat", False)
    at = AppTest.from_function(_cards_app, default_timeout=30).run()
    assert not at.button                                    # flaga wyłączona -> brak przycisków
    monkeypatch.setitem(FEATURES, "dm_chat", True)
    at = AppTest.from_function(_cards_app, default_timeout=30).run()
    assert [b.key for b in at.button] == ["m5_t_card_u_kuba"]   # bez przycisku przy sobie
    at.button(key="m5_t_card_u_kuba").click().run()
    assert at.session_state["chat_room_id"] == OLA_KUBA

