"""M5 — testy logiki czatu (bez UI)."""

import string

import pytest

from m5_chat.service import MAX_MESSAGE_LEN, escape_markdown, room_title, safe_avatar_src, send_message
from shared.models import dm_room_id, event_room_id
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
    assert "Ola" in room_title(storage, dm_room_id("u_ola", "u_kuba"))


def test_seeded_chat_is_visible(storage: Storage):
    assert storage.count_messages(event_room_id("e_jazz_alchemia")) >= 3


def test_escape_markdown_shows_text_literally():
    raw = "**Boss** _x_ [klik](javascript:alert(1)) <b>x</b> $x$ :red[x] # \\"
    escaped = escape_markdown(raw)
    # każdy znak interpunkcyjny ASCII dostaje dokładnie jeden backslash przed sobą
    expected = "".join("\\" + ch if ch in string.punctuation else ch for ch in raw)
    assert escaped == expected
    assert escape_markdown("Michał Żak") == "Michał Żak"


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
