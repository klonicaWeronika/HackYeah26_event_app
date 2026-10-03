"""
M5 — logika czatu i interakcji (bez streamlit -> testowalna pytestem).

Publiczne API (kontrakt):
    send_message(storage, room_id, user_id, text) -> ChatMessage | None
    room_title(storage, room_id) -> str
"""

from __future__ import annotations

from shared.models import ChatMessage
from shared.storage import Storage

MAX_MESSAGE_LEN = 500


def send_message(storage: Storage, room_id: str, user_id: str, text: str) -> ChatMessage | None:
    """Waliduje i zapisuje wiadomość. Pusta wiadomość -> None (nic nie zapisujemy)."""
    clean = text.strip()
    if not clean:
        return None
    return storage.post_message(room_id, user_id, clean[:MAX_MESSAGE_LEN])


def room_title(storage: Storage, room_id: str) -> str:
    kind, _, rest = room_id.partition(":")
    if kind == "event":
        event = storage.get_event(rest)
        return f"{event.meta.emoji} {event.title}" if event else "Czat wydarzenia"
    if kind == "dm":
        names = [u.name for u in storage.get_users(rest.split(":")).values()]
        return "💬 " + " & ".join(names)
    return room_id
