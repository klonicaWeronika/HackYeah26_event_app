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


def _chat_app(event_id: str = "e_jazz_alchemia"):
    from m5_chat.chat_view import render_chat_room
    from shared import state
    from shared.models import event_room_id
    from shared.storage import get_storage

    storage = get_storage()
    state.init()   # zalogowana: u_ola (domyślna)
    render_chat_room(storage, storage.get_user(state.current_user_id()), event_room_id(event_id))


def _html_blocks(at: AppTest) -> list[str]:
    return [el.value for el in at.get("html")]


def _button_keys(at: AppTest) -> set[str]:
    return {b.key for b in at.button}


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


def test_own_messages_are_right_aligned_without_avatar(chat_app: AppTest, storage: Storage):
    m1 = storage.post_message(ROOM, "u_ola", "pierwsza")
    m2 = storage.post_message(ROOM, "u_ola", "druga")
    at = chat_app.run()
    mine = [h for h in _html_blocks(at) if "m5-mine" in h]
    assert len(mine) == 1 and "pierwsza" in mine[0] and "druga" in mine[0]
    keys = _button_keys(at)
    assert not {f"m5_name_{m1.id}", f"m5_name_{m2.id}"} & keys
    assert not any(k.startswith(_avatar_key_prefix("u_ola")) for k in keys)


def test_consecutive_messages_of_one_author_share_one_header(chat_app: AppTest, storage: Storage):
    k1 = storage.post_message(ROOM, "u_kuba", "raz")
    k2 = storage.post_message(ROOM, "u_kuba", "dwa")
    at = chat_app.run()
    keys = _button_keys(at)
    assert f"m5_name_{k1.id}" in keys and f"m5_name_{k2.id}" not in keys
    assert any("raz" in h and "dwa" in h and "m5-mine" not in h for h in _html_blocks(at))


def test_message_text_is_rendered_literally(chat_app: AppTest, storage: Storage):
    storage.post_message(ROOM, "u_kuba", "<b>x</b> **y** <img src=x onerror=alert(1)>")
    at = chat_app.run()
    block = next(h for h in _html_blocks(at) if "**y**" in h)
    assert "&lt;b&gt;x&lt;/b&gt; **y** &lt;img src=x onerror=alert(1)&gt;" in block
    assert "<b>" not in block and "<img" not in block


def test_empty_room_shows_placeholder(storage: Storage, monkeypatch):
    monkeypatch.setattr("shared.storage._default_storage", storage)
    at = AppTest.from_function(_chat_app, kwargs={"event_id": "e_ceramika"}, default_timeout=30).run()
    assert not at.exception, at.exception
    assert any("Jeszcze cisza" in h for h in _html_blocks(at))
