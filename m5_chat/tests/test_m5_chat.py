"""M5 — testy logiki czatu (bez UI)."""

import string
from datetime import datetime, timedelta

import pytest

from m5_chat.service import (
    MAX_MESSAGE_LEN, MAX_MESSAGE_LINES, POLL_OVERLAP, css_string, escape_markdown, group_messages,
    merge_messages, refresh_messages, room_title, safe_avatar_src, sanitize_text, seconds_until_allowed,
    send_message,
)
from shared.models import ChatMessage, dm_room_id, event_room_id, group_room_id
from shared.storage import Storage


def test_send_message_strips_and_rejects_empty(storage: Storage):
    room = event_room_id("e_ceramika")
    assert send_message(storage, room, "u_zosia", "   ") is None
    msg = send_message(storage, room, "u_zosia", "  hej!  ")
    assert msg.text == "hej!"
    assert storage.list_messages(room)[-1].id == msg.id


def test_send_message_truncates(storage: Storage):
    msg = send_message(storage, event_room_id("e_ceramika"), "u_zosia", "x" * 2000)
    assert len(msg.text) == MAX_MESSAGE_LEN


def test_room_titles(storage: Storage):
    assert "Jam session" in room_title(storage, event_room_id("e_jazz_alchemia"))
    jazz = room_title(storage, event_room_id("e_jazz_alchemia"))
    assert room_title(storage, group_room_id("g_jazz")) == jazz                 # czat grupy = nazwa wydarzenia
    assert "Ola" in room_title(storage, dm_room_id("u_ola", "u_kuba"))


def test_seeded_group_chat_is_visible(storage: Storage):
    assert storage.count_messages(group_room_id("g_jazz")) >= 3


def test_escape_markdown_shows_text_literally():
    raw = "**Boss** _x_ [klik](javascript:alert(1)) <b>x</b> $x$ :red[x] # \\"
    escaped = escape_markdown(raw)
    # każdy znak interpunkcyjny ASCII dostaje dokładnie jeden backslash przed sobą
    expected = "".join("\\" + ch if ch in string.punctuation else ch for ch in raw)
    assert escaped == expected
    assert escape_markdown("Michał Żak") == "Michał Żak"


def test_css_string_cannot_break_out_of_css():
    assert css_string("KU") == "KU"
    assert css_string('"Ż') == r"\22 \17b "
    escaped = css_string('x" </style>\\\n')
    assert escaped == r"x\22 \20 \3c \2f style\3e \5c \a "
    assert not set('"<>\n').intersection(escaped)


@pytest.mark.parametrize("url", [
    "https://i.pravatar.cc/150?img=5",
    "http://example.com/a/b.png",
    "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
    "data:image/png;base64,iVBORw0KGgo=",
])
def test_safe_avatar_src_accepts_images(url):
    assert safe_avatar_src(url) == url


@pytest.mark.parametrize("url", [
    None,
    "",
    'https://x.pl/a.png"); } body {display:none} /*',
    "https://x.pl/</style><b>x</b>",
    "https://x.pl/a b.png",
    "https://x.pl/a\\\".png",
    "javascript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD4=",
    "data:image/svg+xml;base64,PHN2Zz4=",
])
def test_safe_avatar_src_rejects_unsafe(url):
    assert safe_avatar_src(url) is None


def _msg(user_id: str, at: datetime) -> ChatMessage:
    return ChatMessage(room_id=event_room_id("e_x"), user_id=user_id, text="hej", created_at=at)


def _shape(groups: list[list[ChatMessage]]) -> list[tuple[str, int]]:
    return [(g[0].user_id, len(g)) for g in groups]


def test_group_messages_joins_consecutive_messages_of_one_author():
    t = datetime(2026, 10, 3, 18, 0)
    msgs = [_msg("u_kuba", t), _msg("u_kuba", t + timedelta(minutes=1)), _msg("u_ola", t + timedelta(minutes=2)),
            _msg("u_kuba", t + timedelta(minutes=3)), _msg("u_kuba", t + timedelta(minutes=4))]
    assert _shape(group_messages(msgs)) == [("u_kuba", 2), ("u_ola", 1), ("u_kuba", 2)]


def test_group_messages_splits_on_long_pause_and_new_day():
    t = datetime(2026, 10, 3, 23, 50)
    msgs = [
        _msg("u_kuba", t),                              # 23:50
        _msg("u_kuba", t + timedelta(minutes=6)),       # 23:56 — przerwa 6 min > 5 -> nowa grupa
        _msg("u_kuba", t + timedelta(minutes=9)),       # 23:59 — ta sama grupa
        _msg("u_kuba", t + timedelta(minutes=11)),      # 00:01 — tylko 2 min, ale nowy dzień -> nowa grupa
    ]
    assert _shape(group_messages(msgs)) == [("u_kuba", 1), ("u_kuba", 2), ("u_kuba", 1)]
    assert group_messages([]) == []


JAZZ = group_room_id("g_jazz")   # mocki: msg_seed_000..002 (Kuba, Bartek, Natalia)


def test_refresh_messages_loads_once_then_asks_only_for_new(storage: Storage, monkeypatch):
    since_args = []
    list_messages = storage.list_messages

    def spy(room_id, **kwargs):
        since_args.append(kwargs.get("since"))
        return list_messages(room_id, **kwargs)

    monkeypatch.setattr(storage, "list_messages", spy)
    buf = refresh_messages(storage, JAZZ, [])
    assert [m.id for m in buf] == ["msg_seed_000", "msg_seed_001", "msg_seed_002"]

    new = storage.post_message(JAZZ, "u_kuba", "nowa")
    buf2 = refresh_messages(storage, JAZZ, buf)
    assert [m.id for m in buf2] == [*(m.id for m in buf), new.id]
    assert since_args == [None, buf[-1].created_at - POLL_OVERLAP]


def test_refresh_messages_without_news_returns_same_buffer(storage: Storage):
    buf = refresh_messages(storage, JAZZ, [])
    assert refresh_messages(storage, JAZZ, buf) is buf


def test_refresh_messages_catches_message_committed_late(storage: Storage):
    buf = refresh_messages(storage, JAZZ, [])
    newest = storage.post_message(JAZZ, "u_kuba", "B")
    buf = refresh_messages(storage, JAZZ, buf)
    # zapis z innego wątku/procesu: starszy znacznik czasu, ale trafia do bazy dopiero teraz
    late = storage.add_message(ChatMessage(
        room_id=JAZZ, user_id="u_ola", text="A", created_at=newest.created_at - timedelta(seconds=2),
    ))
    buf = refresh_messages(storage, JAZZ, buf)
    assert [m.id for m in buf[-2:]] == [late.id, newest.id]


def test_merge_messages_dedupes_sorts_and_trims():
    t = datetime(2026, 10, 3, 18, 0)
    a, b, c = (_msg("u_kuba", t + timedelta(minutes=i)) for i in range(3))
    assert merge_messages([a, b], [c, b], limit=2) == [b, c]
    assert merge_messages([b], [a]) == [a, b]
    buf = [a, b]
    assert merge_messages(buf, [a, b]) is buf


def test_sanitize_text_drops_invisible_controls_but_keeps_content():
    raw = "  <b>x</b> **y**\x00\x1b[31m\u202eabc\u2066  \r\n\r\n\r\n\r\nzażółć 👩\u200d👧\tok  "
    # HTML i markdown zostają (widok wyświetla je dosłownie); znika: NUL, ESC, bidi override/isolate,
    # nadmiar pustych linii i spacji na końcach linii; łącznik emoji (ZWJ) zostaje
    assert sanitize_text(raw) == "<b>x</b> **y**[31mabc\n\nzażółć 👩\u200d👧\tok"


def test_sanitize_text_limits_lines_and_length():
    lines = sanitize_text("\n".join(str(i) for i in range(30))).split("\n")
    assert len(lines) == MAX_MESSAGE_LINES
    assert lines[-1] == " ".join(str(i) for i in range(MAX_MESSAGE_LINES - 1, 30))
    assert len(sanitize_text("ż" * 2000)) == MAX_MESSAGE_LEN


def test_send_message_rejects_text_made_only_of_controls(storage: Storage):
    room = event_room_id("e_ceramika")
    assert send_message(storage, room, "u_zosia", "\x00\u202e \n\t ") is None
    assert storage.count_messages(room) == 0


def test_seconds_until_allowed():
    assert seconds_until_allowed(None, 100.0) == 0
    assert seconds_until_allowed(100.0, 100.4) == pytest.approx(0.6)
    assert seconds_until_allowed(100.0, 101.0) == 0
    assert seconds_until_allowed(100.0, 250.0) == 0

