"""
M5 — logika czatu i interakcji (bez streamlit -> testowalna pytestem).

Publiczne API (kontrakt):
    send_message(storage, room_id, user_id, text) -> ChatMessage | None
    room_title(storage, room_id) -> str
Pomocnicze (bezpieczne wyświetlanie danych użytkownika, układ czatu):
    escape_markdown(text) -> str
    css_string(text) -> str
    safe_avatar_src(url) -> str | None
    group_messages(messages, gap=GROUP_GAP) -> list[list[ChatMessage]]
Polling przyrostowy (bufor wiadomości pokoju trzymany przez UI w session_state):
    refresh_messages(storage, room_id, buffer) -> list[ChatMessage]
    merge_messages(buffer, fresh) -> list[ChatMessage]
"""

from __future__ import annotations

import re
import string
from collections.abc import Iterable
from datetime import timedelta

from shared.models import ChatMessage
from shared.storage import Storage

MAX_MESSAGE_LEN = 500
GROUP_GAP = timedelta(minutes=5)   # dłuższa przerwa = nowy nagłówek (awatar + imię), nawet u tej samej osoby
BUFFER_LIMIT = 300                 # tyle ostatnich wiadomości pokoju trzymamy w pamięci sesji
# `created_at` nadaje się PRZED zapisem, więc wiadomość z innego wątku/procesu może trafić do bazy
# chwilę po nowszej. Polling sięga więc trochę wstecz, a duplikaty odsiewa po id.
POLL_OVERLAP = timedelta(seconds=10)

# Adres zdjęcia trafia do CSS `url("...")` -> dopuszczamy tylko znaki, które nie wyjdą z cudzysłowu/reguły.
_SAFE_HTTP_URL = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&*+,;=%]+")
_SAFE_DATA_URI = re.compile(r"data:image/(?:png|jpe?g|webp|gif);base64,[A-Za-z0-9+/]+={0,2}")
_MD_ESCAPES = str.maketrans({c: "\\" + c for c in string.punctuation})


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


def escape_markdown(text: str) -> str:
    """Tekst dosłownie w miejscach renderujących markdown (etykiety przycisków, tooltipy).

    CommonMark pozwala poprzedzić backslashem każdy znak interpunkcyjny ASCII, więc
    '**x**', '[a](b)', '<b>', '$x$' czy ':red[x]' wyświetlą się jako zwykły tekst.
    """
    return text.translate(_MD_ESCAPES)


def css_string(text: str) -> str:
    """Tekst do wstawienia w CSS `content: "..."`: wszystko poza ASCII [A-Za-z0-9] jako escape `\\hex `.

    Cudzysłów, backslash, nowa linia ani '</style>' nie wyjdą poza napis.
    """
    return "".join(c if c.isascii() and c.isalnum() else f"\\{ord(c):x} " for c in text)


def safe_avatar_src(url: str | None) -> str | None:
    """Adres zdjęcia bezpieczny do wstawienia w CSS albo None (wtedy awatar z inicjałami).

    Dopuszcza http(s) bez cudzysłowów, nawiasów, spacji i '<>' oraz data URI obrazka w base64
    (format awatarów z uploadu M3).
    """
    if not url:
        return None
    url = url.strip()
    if _SAFE_HTTP_URL.fullmatch(url) or _SAFE_DATA_URI.fullmatch(url):
        return url
    return None


def group_messages(messages: Iterable[ChatMessage], *, gap: timedelta = GROUP_GAP) -> list[list[ChatMessage]]:
    """Kolejne wiadomości tej samej osoby -> jedna grupa (jeden nagłówek z awatarem i imieniem).

    Nową grupę zaczyna: inny autor, przerwa dłuższa niż `gap` albo zmiana dnia.
    Wejście posortowane rosnąco po czasie (tak zwraca `Storage.list_messages`).
    """
    groups: list[list[ChatMessage]] = []
    for msg in messages:
        prev = groups[-1][-1] if groups else None
        if (
            prev is not None
            and prev.user_id == msg.user_id
            and msg.created_at - prev.created_at <= gap
            and msg.created_at.date() == prev.created_at.date()
        ):
            groups[-1].append(msg)
        else:
            groups.append([msg])
    return groups


def merge_messages(
    buffer: list[ChatMessage], fresh: Iterable[ChatMessage], *, limit: int = BUFFER_LIMIT
) -> list[ChatMessage]:
    """Bufor + nowe wiadomości: bez duplikatów (po id), rosnąco po czasie, najwyżej `limit` ostatnich.

    Gdy nic nowego nie przyszło, zwraca TEN SAM obiekt `buffer` (tani test „czy coś się zmieniło”).
    """
    known = {m.id for m in buffer}
    new = [m for m in fresh if m.id not in known]
    if not new:
        return buffer
    merged = sorted([*buffer, *new], key=lambda m: (m.created_at, m.id))
    return merged[-limit:]


def refresh_messages(
    storage: Storage, room_id: str, buffer: list[ChatMessage], *, limit: int = BUFFER_LIMIT
) -> list[ChatMessage]:
    """Polling przyrostowy: pusty bufor -> ostatnie `limit` wiadomości pokoju;
    w przeciwnym razie z bazy idą tylko wiadomości nowsze niż ostatnia w buforze (minus POLL_OVERLAP).
    """
    if not buffer:
        return storage.list_messages(room_id, limit=limit)
    since = buffer[-1].created_at - POLL_OVERLAP
    return merge_messages(buffer, storage.list_messages(room_id, since=since, limit=limit), limit=limit)
