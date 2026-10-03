"""M5 — testy widoku czatu przez streamlit AppTest (izolowana baza w RAM, bez przeglądarki)."""

import pytest
from streamlit.testing.v1 import AppTest

from m5_chat.chat_view import SHOW_STEP, _avatar_key_prefix
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


def _header_key(user_id: str, first_msg_id: str) -> str:
    """Klucz przycisku-nagłówka grupy (awatar + imię autora)."""
    return f"{_avatar_key_prefix(user_id)}{first_msg_id}"


@pytest.mark.parametrize("msg_id, author_id", [("msg_seed_000", "u_kuba"), ("msg_seed_001", "u_bartek")])
def test_click_author_header_opens_profile(chat_app: AppTest, msg_id: str, author_id: str):
    at = chat_app.run()
    at.button(key=_header_key(author_id, msg_id)).click().run()
    assert not at.exception, at.exception
    assert at.session_state["view"] == View.PROFILE_VIEW
    assert at.session_state["viewed_user_id"] == author_id


def test_unknown_author_is_not_clickable(chat_app: AppTest, storage: Storage):
    msg = storage.post_message(ROOM, "u_usuniety", "hej")
    at = chat_app.run()
    assert at.button(key=_header_key("u_usuniety", msg.id)).disabled
    assert not at.button(key=_header_key("u_kuba", "msg_seed_000")).disabled


def test_profile_links_follow_feature_flag(chat_app: AppTest, monkeypatch):
    monkeypatch.setitem(FEATURES, "profile_view", False)
    at = chat_app.run()
    assert at.button(key=_header_key("u_kuba", "msg_seed_000")).disabled


def test_author_name_is_escaped_in_button_label(chat_app: AppTest, storage: Storage):
    evil = storage.upsert_user(User(id="u_evil", name="**Boss** [klik](javascript:x)"))
    msg = storage.post_message(ROOM, evil.id, "<b>x</b>")
    at = chat_app.run()
    assert at.button(key=_header_key(evil.id, msg.id)).label == f"**{escape_markdown(evil.name)}**"


def test_own_messages_are_right_aligned_without_avatar(chat_app: AppTest, storage: Storage):
    storage.post_message(ROOM, "u_ola", "pierwsza")
    storage.post_message(ROOM, "u_ola", "druga")
    at = chat_app.run()
    mine = [h for h in _html_blocks(at) if "m5-mine" in h]
    assert len(mine) == 1 and "pierwsza" in mine[0] and "druga" in mine[0]
    assert not any(k.startswith(_avatar_key_prefix("u_ola")) for k in _button_keys(at))


def test_consecutive_messages_of_one_author_share_one_header(chat_app: AppTest, storage: Storage):
    k1 = storage.post_message(ROOM, "u_kuba", "raz")
    k2 = storage.post_message(ROOM, "u_kuba", "dwa")
    at = chat_app.run()
    keys = _button_keys(at)
    assert _header_key("u_kuba", k1.id) in keys and _header_key("u_kuba", k2.id) not in keys
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


def _bubble_count(at: AppTest) -> int:
    return sum(h.count('class="m5-bubble"') for h in _html_blocks(at))


def test_room_messages_are_kept_in_session_buffer(chat_app: AppTest):
    at = chat_app.run()
    assert [m.id for m in at.session_state[f"m5_buf_{ROOM}"]] == ["msg_seed_000", "msg_seed_001", "msg_seed_002"]


def test_only_latest_messages_are_drawn_older_on_demand(chat_app: AppTest, storage: Storage):
    for i in range(120):
        storage.post_message(ROOM, "u_kuba" if i % 2 else "u_bartek", f"m{i}")   # 123 w pokoju
    at = chat_app.run()
    assert _bubble_count(at) == SHOW_STEP
    at.button(key=f"m5_older_{ROOM}").click().run()
    assert _bubble_count(at) == 2 * SHOW_STEP
    at.button(key=f"m5_older_{ROOM}").click().run()
    assert _bubble_count(at) == 123
    assert f"m5_older_{ROOM}" not in _button_keys(at)


def test_full_rerun_resyncs_buffer_after_demo_reset(chat_app: AppTest, storage: Storage):
    storage.post_message(ROOM, "u_kuba", "sprzed resetu")
    at = chat_app.run()
    assert any("sprzed resetu" in h for h in _html_blocks(at))
    storage.reset()   # „🔄 Reset danych demo” w nagłówku M1 -> pełny rerun
    at.run()
    assert not any("sprzed resetu" in h for h in _html_blocks(at))


def test_tick_time_shown_only_in_debug_mode(chat_app: AppTest):
    at = chat_app.run()
    assert at.session_state["m5_tick_ms"] > 0
    assert not any("tick" in c.value for c in at.caption)
    at.query_params["m5_debug"] = "1"
    at.run()
    assert any("tick" in c.value for c in at.caption)
