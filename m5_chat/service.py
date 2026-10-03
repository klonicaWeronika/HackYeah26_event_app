"""
M5 — logika czatu i interakcji (bez streamlit -> testowalna pytestem).

Publiczne API (kontrakt):
    send_message(storage, room_id, user_id, text) -> ChatMessage | None
    room_title(storage, room_id, *, viewer_id=None) -> str
    can_post(storage, room_id, user_id) -> bool
Prywatne rozmowy (DM):
    dm_participants(room_id) -> tuple[str, str] | None
    can_access_room(room_id, user_id) -> bool
    list_conversations(storage, user_id) -> list[Conversation]
Grupy na wydarzenia (czat grupy, zaproszenia, głosowania): m5_chat/groups.py
Anty-spam i higiena tekstu:
    sanitize_text(text) -> str
    seconds_until_allowed(last_sent_at, now) -> float
Pomocnicze (bezpieczne wyświetlanie danych użytkownika, układ czatu):
    escape_markdown(text) -> str
    css_string(text) -> str
    safe_avatar_src(url) -> str | None
    group_messages(messages, gap=GROUP_GAP) -> list[list[ChatMessage]]
Polling przyrostowy (bufor wiadomości pokoju trzymany przez UI w session_state):
    refresh_messages(storage, room_id, buffer) -> list[ChatMessage]
    merge_messages(buffer, fresh) -> list[ChatMessage]
Zapisy na wydarzenia („Idę!” / „Interesuje mnie”):
    set_attendance(storage, user_id, event_id, status, *, open_to_meet=None) -> Attendance | None
    attendance_counts(storage, event_id) -> dict[AttendanceStatus, int]
"""

from __future__ import annotations

import re
import string
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta

from m5_chat.groups import GroupRole, group_id_of_room, role_in
from shared.models import Attendance, AttendanceStatus, ChatMessage, User, dm_room_id
from shared.storage import Storage

MAX_MESSAGE_LEN = 500
MAX_MESSAGE_LINES = 20             # dłuższe wiadomości sklejamy (pionowy „flood” jedną wiadomością)
MIN_SEND_INTERVAL = 1.0            # s — najwyżej 1 wiadomość na sekundę z jednej sesji
GROUP_GAP = timedelta(minutes=5)   # dłuższa przerwa = nowy nagłówek (awatar + imię), nawet u tej samej osoby
BUFFER_LIMIT = 300                 # tyle ostatnich wiadomości pokoju trzymamy w pamięci sesji
# `created_at` nadaje się PRZED zapisem, więc wiadomość z innego wątku/procesu może trafić do bazy
# chwilę po nowszej. Polling sięga więc trochę wstecz, a duplikaty odsiewa po id.
POLL_OVERLAP = timedelta(seconds=10)

# Adres zdjęcia trafia do CSS `url("...")` -> dopuszczamy tylko znaki, które nie wyjdą z cudzysłowu/reguły.
_SAFE_HTTP_URL = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&*+,;=%]+")
_SAFE_DATA_URI = re.compile(r"data:image/(?:png|jpe?g|webp|gif);base64,[A-Za-z0-9+/]+={0,2}")
_MD_ESCAPES = str.maketrans({c: "\\" + c for c in string.punctuation})
# Znaki sterujące (poza \t i \n) oraz sterowanie kierunkiem tekstu (bidi override/isolate) —
# te drugie pozwalają „odwrócić” fragment wiadomości i podszyć się pod inną treść.
_INVISIBLE_CONTROLS = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def sanitize_text(text: str) -> str:
    """Tekst wiadomości gotowy do zapisu: bez znaków sterujących, najwyżej jedna pusta linia z rzędu,
    najwyżej MAX_MESSAGE_LINES linii i MAX_MESSAGE_LEN znaków. Treść (HTML, markdown) zostaje bez zmian —
    o dosłowne wyświetlanie dba widok (html.escape)."""
    text = _INVISIBLE_CONTROLS.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(line.rstrip() for line in text.split("\n"))).strip()
    lines = text.split("\n")
    if len(lines) > MAX_MESSAGE_LINES:
        text = "\n".join(lines[: MAX_MESSAGE_LINES - 1] + [" ".join(lines[MAX_MESSAGE_LINES - 1:])])
    return text[:MAX_MESSAGE_LEN].rstrip()


def seconds_until_allowed(
    last_sent_at: float | None, now: float, *, min_interval: float = MIN_SEND_INTERVAL
) -> float:
    """Anty-flood: 0 = można wysłać; > 0 = ile sekund trzeba jeszcze odczekać od poprzedniej wiadomości.

    Czasy z zegara monotonicznego (`time.monotonic()`), trzymane przez UI w session_state.
    """
    if last_sent_at is None:
        return 0.0
    return max(0.0, min_interval - (now - last_sent_at))


def send_message(storage: Storage, room_id: str, user_id: str, text: str) -> ChatMessage | None:
    """Czyści (sanitize_text) i zapisuje wiadomość. None (nic nie zapisujemy), gdy po czyszczeniu
    jest pusta albo nadawca nie może pisać w pokoju (cudzy DM, grupa, do której nie należy)."""
    clean = sanitize_text(text)
    if not clean or not can_post(storage, room_id, user_id):
        return None
    return storage.post_message(room_id, user_id, clean)


def can_post(storage: Storage, room_id: str, user_id: str) -> bool:
    """Czy osoba może pisać w pokoju: w grupie tylko członkowie (zaproszeni tylko czytają)."""
    if (group_id := group_id_of_room(room_id)) is not None:
        return role_in(storage.get_group(group_id), user_id) is GroupRole.MEMBER
    return can_access_room(room_id, user_id)


def room_title(storage: Storage, room_id: str, *, viewer_id: str | None = None) -> str:
    """Tytuł pokoju do nagłówka: nazwa wydarzenia (czat wydarzenia i grupy); DM oglądany
    przez uczestnika (`viewer_id`) = imię rozmówcy."""
    kind, _, rest = room_id.partition(":")
    if kind == "group":
        group = storage.get_group(rest)
        rest, kind = (group.event_id if group else ""), "event"
    if kind == "event":
        event = storage.get_event(rest)
        return f"{event.meta.emoji} {event.title}" if event else "Czat wydarzenia"
    if kind == "dm":
        ids = list(dm_participants(room_id) or ())
        if viewer_id in ids and len(set(ids)) == 2:
            ids.remove(viewer_id)
        names = [u.name for u in storage.get_users(ids).values()]
        return "💬 " + " & ".join(names) if names else "💬 Prywatna rozmowa"
    return room_id


# --------------------------------------------------------------------------- #
# Prywatne rozmowy (DM)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Conversation:
    """Pozycja listy „Moje rozmowy”."""

    room_id: str
    other: User
    last: ChatMessage


def dm_participants(room_id: str) -> tuple[str, str] | None:
    """('u_a', 'u_b') dla pokoju z dm_room_id(); None dla innych pokojów i źle zbudowanych ID."""
    kind, _, rest = room_id.partition(":")
    a, sep, b = rest.partition(":")
    return (a, b) if kind == "dm" and sep and a and b else None


def can_access_room(room_id: str, user_id: str) -> bool:
    """DM tylko dla jego dwóch uczestników; inne pokoje bez ograniczeń na poziomie ID
    (dostęp do czatu grupy zależy od jej składu -> `can_post` / `groups.role_in`)."""
    if not room_id.startswith("dm:"):
        return True
    participants = dm_participants(room_id)
    return participants is not None and user_id in participants


def list_conversations(storage: Storage, user_id: str) -> list[Conversation]:
    """Moje DM-y z co najmniej jedną wiadomością, od najświeższej.

    Storage nie ma listy pokojów, więc pytamy o ostatnią wiadomość w DM z każdą osobą
    (zapytanie po indeksie room_id, ~kilkadziesiąt µs; przy kilkudziesięciu osobach to ~ms).
    """
    conversations = []
    for other in storage.list_users():
        if other.id == user_id:
            continue
        room_id = dm_room_id(user_id, other.id)
        if last := storage.list_messages(room_id, limit=1):
            conversations.append(Conversation(room_id, other, last[-1]))
    conversations.sort(key=lambda c: c.last.created_at, reverse=True)
    return conversations


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


def set_attendance(
    storage: Storage,
    user_id: str,
    event_id: str,
    status: AttendanceStatus | None,
    *,
    open_to_meet: bool | None = None,
) -> Attendance | None:
    """Zapis, zmiana statusu albo rezygnacja (`status=None`) jednym wywołaniem.

    `open_to_meet=None` zachowuje dotychczasową zgodę na pokazanie w dopasowaniach
    (nowy zapis: True — od razu widoczny u innych w `match_for_event`).
    """
    if status is None:
        storage.leave_event(user_id, event_id)
        return None
    if open_to_meet is None:
        current = storage.get_attendance(user_id, event_id)
        open_to_meet = current.open_to_meet if current else True
    return storage.join_event(user_id, event_id, status=status, open_to_meet=open_to_meet)


def attendance_counts(storage: Storage, event_id: str) -> dict[AttendanceStatus, int]:
    """Liczba zapisanych na wydarzenie w podziale na status (snapshot w RAM, bez SQL)."""
    counts = dict.fromkeys(AttendanceStatus, 0)
    for attendance in storage.list_attendees(event_id):
        counts[attendance.status] += 1
    return counts
