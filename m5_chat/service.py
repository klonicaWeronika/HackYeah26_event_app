"""
M5 — logika czatu i interakcji (bez streamlit -> testowalna pytestem).

Publiczne API (kontrakt):
    send_message(storage, room_id, user_id, text) -> ChatMessage | None
    room_title(storage, room_id) -> str
Pomocnicze (bezpieczne wyświetlanie danych użytkownika):
    escape_markdown(text) -> str
    safe_avatar_src(url) -> str | None
"""

from __future__ import annotations

import re
import string

from shared.models import ChatMessage
from shared.storage import Storage

MAX_MESSAGE_LEN = 500

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
