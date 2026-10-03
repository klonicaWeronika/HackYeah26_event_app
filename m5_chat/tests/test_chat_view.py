"""M5 — testy widoku czatu przez streamlit AppTest (izolowana baza w RAM, bez przeglądarki)."""

import pytest
from streamlit.testing.v1 import AppTest

from m5_chat.chat_view import _avatar_key_prefix
from m5_chat.service import escape_markdown
from shared.config import FEATURES
from shared.models import User, event_room_id
from shared.state import View
from shared.storage import Storage

ROOM = event_room_id("e_jazz_alchemia")   # mocki: msg_seed_000 = Kuba, msg_seed_001 = Bartek


def _chat_app():
    from m5_chat.chat_view import render_chat_room
    from shared import state
    from shared.models import event_room_id
    from shared.storage import get_storage

    storage = get_storage()
    state.init()
    render_chat_room(storage, storage.get_user(state.current_user_id()), event_room_id("e_jazz_alchemia"))


@pytest.fixture
def chat_app(storage: Storage, monkeypatch) -> AppTest:
    monkeypatch.setattr("shared.storage._default_storage", storage)
    return AppTest.from_function(_chat_app, default_timeout=30)


def test_click_author_name_opens_profile(chat_app: AppTest):
    at = chat_app.run()
    at.button(key="m5_name_msg_seed_000").click().run()
    assert not at.exception, at.exception
    assert at.session_state["view"] == View.PROFILE_VIEW
    assert at.session_state["viewed_user_id"] == "u_kuba"


def test_click_author_avatar_opens_profile(chat_app: AppTest):
    at = chat_app.run()
    at.button(key=f"{_avatar_key_prefix('u_bartek')}msg_seed_001").click().run()
    assert at.session_state["view"] == View.PROFILE_VIEW
    assert at.session_state["viewed_user_id"] == "u_bartek"


def test_unknown_author_is_not_clickable(chat_app: AppTest, storage: Storage):
    msg = storage.post_message(ROOM, "u_usuniety", "hej")
    at = chat_app.run()
    assert at.button(key=f"m5_name_{msg.id}").disabled
    assert at.button(key=f"{_avatar_key_prefix('u_usuniety')}{msg.id}").disabled
    assert not at.button(key="m5_name_msg_seed_000").disabled


def test_profile_links_follow_feature_flag(chat_app: AppTest, monkeypatch):
    monkeypatch.setitem(FEATURES, "profile_view", False)
    at = chat_app.run()
    assert at.button(key="m5_name_msg_seed_000").disabled


def test_author_name_is_escaped_in_button_label(chat_app: AppTest, storage: Storage):
    evil = storage.upsert_user(User(id="u_evil", name="**Boss** [klik](javascript:x)"))
    msg = storage.post_message(ROOM, evil.id, "<b>x</b>")
    at = chat_app.run()
    assert at.button(key=f"m5_name_{msg.id}").label == f"**{escape_markdown(evil.name)}**"
