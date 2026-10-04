"""
shared/storage.py — warstwa danych (DAO) dla całej aplikacji.

Architektura: "SQLite jako źródło prawdy + snapshot w RAM".

  * SQLite (WAL, stdlib, zero instalacji) — trwałość, wiele procesów (app + scraper) naraz.
  * Tabele są dokumentowe: (id, data JSON). Dodanie pola w modelu = zero migracji.
  * Odczyty events/users/attendance idą z niemutowalnego snapshotu w pamięci
    (dict lookup ~µs) — żadnego SQL przy przełączaniu filtrów czy klikaniu pinezek.
  * Unieważnianie cache:
      - zapis przez ten obiekt  -> czyścimy tylko dotkniętą tabelę,
      - zapis z INNEGO procesu  -> wykrywa to `PRAGMA data_version` (np. po uruchomieniu scrapera).
  * Czat NIE jest cache'owany: indeks (room_id, created_at) + zapytanie z `since`.
  * Grupy na wydarzenia (EventGroup) — snapshot jak wyżej; zmiany przez `update_group` (atomowo).

Moduł NIE importuje streamlit — działa w scraperze, testach i REPL.
Użycie:
    from shared.storage import get_storage
    storage = get_storage()                    # singleton procesu (data/app.db): mocki + prawdziwe eventy M2
    storage = Storage(":memory:")              # izolowana baza do testów (seed TYLKO z mocków)

Pusta baza plikowa (i --reset) dostaje mocki, prawdziwe wydarzenia ze snapshotu scrapera M2
(data/seed_events.json) i przykładową społeczność na nich (shared/example_data.py: osoby, zapisy, czaty)
— zespół nie musi niczego scrapować ani mieć internetu.

CLI:
    python -m shared.storage --stats
    python -m shared.storage --reset           # wyczyść bazę: świeże mocki (daty od dziś) + snapshot M2
    python -m shared.storage --example         # dołóż przykładową społeczność do istniejącej bazy
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from shared.models import (
    Attendance,
    AttendanceStatus,
    ChatMessage,
    Event,
    EventGroup,
    FilterCriteria,
    INTEREST_TAGS,
    User,
)

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = Path(os.environ.get("EVENTAPP_DB", PROJECT_ROOT / "data" / "app.db"))
SEED_EVENTS_PATH = PROJECT_ROOT / "data" / "seed_events.json"   # snapshot prawdziwych eventów (M2)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attendance (
    user_id     TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    data        TEXT NOT NULL,
    PRIMARY KEY (user_id, event_id)
);
CREATE INDEX IF NOT EXISTS ix_attendance_event ON attendance(event_id);
CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    room_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_room ON messages(room_id, created_at);
CREATE TABLE IF NOT EXISTS groups (
    id          TEXT PRIMARY KEY,
    event_id    TEXT NOT NULL,
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_groups_event ON groups(event_id);
"""

M = TypeVar("M", bound=BaseModel)


def _ts(dt: datetime) -> str:
    """Stały format ISO -> sortowanie leksykograficzne == chronologiczne."""
    return dt.isoformat(timespec="microseconds")


class _AttendanceIndex:
    """Snapshot tabeli attendance z indeksami w obie strony."""

    def __init__(self, rows: list[Attendance]):
        self.by_event: dict[str, list[Attendance]] = defaultdict(list)
        self.by_user: dict[str, list[Attendance]] = defaultdict(list)
        self.by_pair: dict[tuple[str, str], Attendance] = {}
        for a in rows:
            self.by_event[a.event_id].append(a)
            self.by_user[a.user_id].append(a)
            self.by_pair[(a.user_id, a.event_id)] = a


class _GroupIndex:
    """Snapshot tabeli groups: po id, po wydarzeniu i po osobie (członek / zaproszona)."""

    def __init__(self, rows: list[EventGroup]):
        rows = sorted(rows, key=lambda g: (g.created_at, g.id))
        self.by_id: dict[str, EventGroup] = {g.id: g for g in rows}
        self.by_event: dict[str, list[EventGroup]] = defaultdict(list)
        self.by_member: dict[str, list[EventGroup]] = defaultdict(list)
        self.by_invitee: dict[str, list[EventGroup]] = defaultdict(list)
        for g in rows:
            self.by_event[g.event_id].append(g)
            for user_id in g.members:
                self.by_member[user_id].append(g)
            for invite in g.invites:
                self.by_invitee[invite.user_id].append(g)


class Storage:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH, *, seed_if_empty: bool = True):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Jedno połączenie na proces + RLock: Streamlit obsługuje sesje wątkami.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)

        self._cache: dict[str, Any] = {}
        self._data_version = self._read_data_version()

        if seed_if_empty and self._is_empty():
            self._seed_demo()

    # ------------------------------------------------------------------ #
    # Cache
    # ------------------------------------------------------------------ #

    def _read_data_version(self) -> int:
        return self._conn.execute("PRAGMA data_version").fetchone()[0]

    def _cached(self, key: str, loader: Callable[[], Any]) -> Any:
        with self._lock:
            version = self._read_data_version()
            if version != self._data_version:      # ktoś inny (np. scraper) zapisał do bazy
                self._data_version = version
                self._cache.clear()
            if key not in self._cache:
                self._cache[key] = loader()
            return self._cache[key]

    def _invalidate(self, *keys: str) -> None:
        for key in keys:
            self._cache.pop(key, None)

    def invalidate_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def _load_models(self, sql: str, model: type[M]) -> list[M]:
        out: list[M] = []
        for (data,) in self._conn.execute(sql):
            try:
                out.append(model.model_validate_json(data))
            except ValidationError as exc:     # rekord niezgodny z modelem nie wywraca aplikacji
                log.warning("Pomijam niepoprawny rekord %s: %s", model.__name__, exc.errors()[:1])
        return out

    def _write(self, sql: str, params: Iterable[tuple] | tuple, *, many: bool = False) -> int:
        with self._lock, self._conn:
            cur = self._conn.executemany(sql, params) if many else self._conn.execute(sql, params)
            return cur.rowcount

    # ------------------------------------------------------------------ #
    # Events
    # ------------------------------------------------------------------ #

    def _events_snapshot(self) -> dict[str, Event]:
        def load() -> dict[str, Event]:
            events = self._load_models("SELECT data FROM events", Event)
            events.sort(key=lambda e: (e.start, e.id))
            return {e.id: e for e in events}

        return self._cached("events", load)

    def list_events(self, criteria: FilterCriteria | None = None) -> list[Event]:
        """Eventy posortowane po dacie rozpoczęcia, opcjonalnie przefiltrowane."""
        events = self._events_snapshot().values()
        if criteria is None:
            return list(events)
        return [e for e in events if criteria.matches(e)]

    def get_event(self, event_id: str) -> Event | None:
        return self._events_snapshot().get(event_id)

    def upsert_event(self, event: Event) -> Event:
        self.upsert_events([event])
        return event

    def upsert_events(self, events: Iterable[Event]) -> int:
        """Bulk insert/update w jednej transakcji (dla scrapera). Zwraca liczbę rekordów."""
        stamp = _ts(datetime.now())
        rows = [(e.id, e.model_dump_json(), stamp) for e in events]
        if rows:
            self._write(
                "INSERT INTO events (id, data, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                rows, many=True,
            )
            self._invalidate("events", "tags")
        return len(rows)

    def delete_event(self, event_id: str) -> bool:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM attendance WHERE event_id = ?", (event_id,))
            self._conn.execute("DELETE FROM groups WHERE event_id = ?", (event_id,))
            deleted = self._conn.execute("DELETE FROM events WHERE id = ?", (event_id,)).rowcount
        self._invalidate("events", "tags", "attendance", "groups")
        return deleted > 0

    def known_tags(self) -> list[str]:
        """Słownik tagów do widgetów: kanoniczne + użyte w eventach i profilach."""
        def load() -> list[str]:
            tags = set(INTEREST_TAGS)
            for e in self._events_snapshot().values():
                tags.update(e.tags)
            for u in self._users_snapshot().values():
                tags.update(u.tags)
            return sorted(tags)

        return list(self._cached("tags", load))

    # ------------------------------------------------------------------ #
    # Users
    # ------------------------------------------------------------------ #

    def _users_snapshot(self) -> dict[str, User]:
        def load() -> dict[str, User]:
            users = self._load_models("SELECT data FROM users", User)
            users.sort(key=lambda u: u.name.lower())
            return {u.id: u for u in users}

        return self._cached("users", load)

    def list_users(self) -> list[User]:
        return list(self._users_snapshot().values())

    def get_user(self, user_id: str | None) -> User | None:
        return self._users_snapshot().get(user_id) if user_id else None

    def get_users(self, user_ids: Iterable[str]) -> dict[str, User]:
        """Batch lookup: {user_id: User} (brakujące ID są pomijane)."""
        snapshot = self._users_snapshot()
        return {uid: snapshot[uid] for uid in user_ids if uid in snapshot}

    def upsert_user(self, user: User) -> User:
        self._write(
            "INSERT INTO users (id, data, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            (user.id, user.model_dump_json(), _ts(datetime.now())),
        )
        self._invalidate("users", "tags")
        return user

    # ------------------------------------------------------------------ #
    # Attendance (zapisy na wydarzenia)
    # ------------------------------------------------------------------ #

    def _attendance_index(self) -> _AttendanceIndex:
        return self._cached(
            "attendance",
            lambda: _AttendanceIndex(self._load_models("SELECT data FROM attendance", Attendance)),
        )

    def join_event(
        self,
        user_id: str,
        event_id: str,
        *,
        status: AttendanceStatus = AttendanceStatus.GOING,
        open_to_meet: bool = True,
    ) -> Attendance:
        """Zapis / aktualizacja zapisu (idempotentne)."""
        existing = self.get_attendance(user_id, event_id)
        att = Attendance(
            user_id=user_id, event_id=event_id, status=status, open_to_meet=open_to_meet,
            **({"created_at": existing.created_at} if existing else {}),
        )
        self._write(
            "INSERT INTO attendance (user_id, event_id, data) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, event_id) DO UPDATE SET data=excluded.data",
            (user_id, event_id, att.model_dump_json()),
        )
        self._invalidate("attendance")
        return att

    def leave_event(self, user_id: str, event_id: str) -> bool:
        deleted = self._write(
            "DELETE FROM attendance WHERE user_id = ? AND event_id = ?", (user_id, event_id)
        )
        self._invalidate("attendance")
        return deleted > 0

    def get_attendance(self, user_id: str, event_id: str) -> Attendance | None:
        return self._attendance_index().by_pair.get((user_id, event_id))

    def list_attendees(self, event_id: str) -> list[Attendance]:
        return list(self._attendance_index().by_event.get(event_id, []))

    def list_user_attendance(self, user_id: str) -> list[Attendance]:
        return list(self._attendance_index().by_user.get(user_id, []))

    def attendee_counts(self) -> dict[str, int]:
        """{event_id: liczba zapisanych} — np. do rozmiaru/etykiety pinezki."""
        return {eid: len(rows) for eid, rows in self._attendance_index().by_event.items()}

    # ------------------------------------------------------------------ #
    # Chat
    # ------------------------------------------------------------------ #

    def add_message(self, message: ChatMessage) -> ChatMessage:
        self._write(
            "INSERT INTO messages (id, room_id, created_at, data) VALUES (?, ?, ?, ?)",
            (message.id, message.room_id, _ts(message.created_at), message.model_dump_json()),
        )
        return message

    def post_message(self, room_id: str, user_id: str, text: str) -> ChatMessage:
        return self.add_message(ChatMessage(room_id=room_id, user_id=user_id, text=text.strip()))

    def list_messages(
        self, room_id: str, *, since: datetime | None = None, limit: int = 200
    ) -> list[ChatMessage]:
        """Ostatnie `limit` wiadomości pokoju, rosnąco po czasie. `since` = tylko nowsze (polling)."""
        sql = "SELECT data FROM messages WHERE room_id = ?"
        params: list[Any] = [room_id]
        if since is not None:
            sql += " AND created_at > ?"
            params.append(_ts(since))
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [ChatMessage.model_validate_json(data) for (data,) in reversed(rows)]

    def count_messages(self, room_id: str) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM messages WHERE room_id = ?", (room_id,)
            ).fetchone()[0]

    # ------------------------------------------------------------------ #
    # Grupy na wydarzenia („ekipy”) — reguły (głosowanie, 1 grupa na event) pilnuje M5
    # ------------------------------------------------------------------ #

    def _group_index(self) -> _GroupIndex:
        return self._cached(
            "groups", lambda: _GroupIndex(self._load_models("SELECT data FROM groups", EventGroup))
        )

    def get_group(self, group_id: str | None) -> EventGroup | None:
        return self._group_index().by_id.get(group_id) if group_id else None

    def list_groups(self, event_id: str | None = None) -> list[EventGroup]:
        """Grupy wydarzenia (albo wszystkie), od najstarszej."""
        index = self._group_index()
        return list(index.by_event.get(event_id, []) if event_id else index.by_id.values())

    def list_member_groups(self, user_id: str) -> list[EventGroup]:
        return list(self._group_index().by_member.get(user_id, []))

    def list_invited_groups(self, user_id: str) -> list[EventGroup]:
        """Grupy z zaproszeniem dla osoby (także te, w których trwa jeszcze głosowanie)."""
        return list(self._group_index().by_invitee.get(user_id, []))

    def upsert_group(self, group: EventGroup) -> EventGroup:
        self._write(
            "INSERT INTO groups (id, event_id, data, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            (group.id, group.event_id, group.model_dump_json(), _ts(datetime.now())),
        )
        self._invalidate("groups")
        return group

    def delete_group(self, group_id: str) -> bool:
        deleted = self._write("DELETE FROM groups WHERE id = ?", (group_id,))
        self._invalidate("groups")
        return deleted > 0

    def update_group(
        self, group_id: str, change: Callable[[EventGroup], EventGroup | None]
    ) -> EventGroup | None:
        """Atomowe read-modify-write (dwie karty głosują naraz -> żaden głos nie ginie).

        `change` dostaje aktualny stan z bazy (nie ze snapshotu) i zwraca nową wersję albo None =
        usuń grupę. Brak grupy -> None bez wywołania `change`. `change` nie może pisać do storage.
        """
        with self._lock, self._conn:
            row = self._conn.execute("SELECT data FROM groups WHERE id = ?", (group_id,)).fetchone()
            if row is None:
                return None
            updated = change(EventGroup.model_validate_json(row[0]))
            if updated is None:
                self._conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
            else:
                self._conn.execute(
                    "UPDATE groups SET data = ?, updated_at = ? WHERE id = ?",
                    (updated.model_dump_json(), _ts(datetime.now()), group_id),
                )
        self._invalidate("groups")
        return updated

    # ------------------------------------------------------------------ #
    # Administracja / seed
    # ------------------------------------------------------------------ #

    def _is_empty(self) -> bool:
        with self._lock:
            return self._conn.execute("SELECT 1 FROM events LIMIT 1").fetchone() is None

    def seed_mocks(self) -> None:
        from shared.mock_data import build_mock_dataset  # lazy: brak cyklicznych importów

        ds = build_mock_dataset()
        self.upsert_events(ds.events)
        for user in ds.users:
            self.upsert_user(user)
        self._write(
            "INSERT OR REPLACE INTO attendance (user_id, event_id, data) VALUES (?, ?, ?)",
            [(a.user_id, a.event_id, a.model_dump_json()) for a in ds.attendance], many=True,
        )
        self._write(
            "INSERT OR REPLACE INTO messages (id, room_id, created_at, data) VALUES (?, ?, ?, ?)",
            [(m.id, m.room_id, _ts(m.created_at), m.model_dump_json()) for m in ds.messages], many=True,
        )
        for group in ds.groups:
            self.upsert_group(group)
        self.invalidate_cache()

    def seed_real_events(self, path: str | Path = SEED_EVENTS_PATH) -> int:
        """Prawdziwe wydarzenia ze snapshotu scrapera M2 (bez sieci). Pomija zakończone. Zwraca liczbę."""
        path = Path(path)
        if not path.exists():
            return 0
        day_start = datetime.combine(datetime.now().date(), datetime.min.time())
        events: list[Event] = []
        for raw in json.loads(path.read_text(encoding="utf-8")):
            try:
                event = Event.model_validate(raw)
            except ValidationError as exc:      # rekord niezgodny z modelem nie blokuje reszty
                log.warning("Pomijam niepoprawny event ze snapshotu: %s", exc.errors()[:1])
                continue
            if event.end_or_start >= day_start:
                events.append(event)
        return self.upsert_events(events)

    def seed_example_data(self) -> str:
        """Przykładowa społeczność (osoby, zapisy, czaty) na prawdziwych eventach z bazy. Idempotentne.

        Zwraca podsumowanie do CLI. Dane i zasady doboru: shared/example_data.py.
        """
        from shared.example_data import build_example_dataset, summary  # lazy: jak seed_mocks

        ds = build_example_dataset(self.list_events(), self.list_users())
        self._write(
            "INSERT OR REPLACE INTO users (id, data, updated_at) VALUES (?, ?, ?)",
            [(u.id, u.model_dump_json(), _ts(datetime.now())) for u in ds.users], many=True,
        )
        self._write(
            "INSERT OR REPLACE INTO attendance (user_id, event_id, data) VALUES (?, ?, ?)",
            [(a.user_id, a.event_id, a.model_dump_json()) for a in ds.attendance], many=True,
        )
        self._write(
            "INSERT OR REPLACE INTO messages (id, room_id, created_at, data) VALUES (?, ?, ?, ?)",
            [(m.id, m.room_id, _ts(m.created_at), m.model_dump_json()) for m in ds.messages], many=True,
        )
        self.invalidate_cache()
        return summary(ds)

    def _seed_demo(self) -> None:
        """Mocki + (dla bazy plikowej) snapshot M2 i społeczność na nim. Testy na :memory: — same mocki."""
        self.seed_mocks()
        if self.db_path != ":memory:":
            self.seed_real_events()
            self.seed_example_data()

    def reset(self, *, seed: bool = True) -> None:
        """Czyści WSZYSTKIE dane (opcjonalnie ładuje mocki + snapshot M2). Do testów i przycisku 'Reset demo'."""
        with self._lock, self._conn:
            for table in ("groups", "messages", "attendance", "users", "events"):
                self._conn.execute(f"DELETE FROM {table}")
        self.invalidate_cache()
        if seed:
            self._seed_demo()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                table: self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("events", "users", "attendance", "messages", "groups")
            }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ---------------------------------------------------------------------- #
# Singleton procesu
# ---------------------------------------------------------------------- #

_default_storage: Storage | None = None
_default_lock = threading.Lock()


def get_storage() -> Storage:
    """Współdzielona instancja dla procesu (wszystkie sesje Streamlit, scraper CLI)."""
    global _default_storage
    with _default_lock:
        if _default_storage is None:
            _default_storage = Storage(DEFAULT_DB_PATH)
        return _default_storage


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Narzędzia bazy demo")
    parser.add_argument("--reset", action="store_true", help="wyczyść bazę i załaduj mocki")
    parser.add_argument("--empty", action="store_true", help="z --reset: NIE ładuj mocków")
    parser.add_argument("--stats", action="store_true", help="pokaż liczbę rekordów")
    parser.add_argument("--example", action="store_true",
                        help="dołóż przykładową społeczność (osoby, zapisy, czaty) na prawdziwych eventach")
    args = parser.parse_args()

    store = get_storage()
    if args.reset:
        store.reset(seed=not args.empty)
        print(f"Zresetowano bazę {store.db_path}")
    if args.example:
        print(f"Przykładowa społeczność: {store.seed_example_data()}")
    print(store.stats())
