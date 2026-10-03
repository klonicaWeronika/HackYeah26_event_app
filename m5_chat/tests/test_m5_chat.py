"""M5 — testy logiki czatu (bez UI)."""

from m5_chat.service import MAX_MESSAGE_LEN, room_title, send_message
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
