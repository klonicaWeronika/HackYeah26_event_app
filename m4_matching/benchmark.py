"""M4-07 — benchmark silnika:  python -m m4_matching.benchmark

Syntetyczne dane 500 eventów × 200 osób (deterministyczne, seed) w osobnym pliku SQLite.
Zapisy (attendance) wstawiamy osobnym połączeniem sqlite3 — tak jak zrobiłby to inny proces
(scraper); Storage wykrywa zmianę przez PRAGMA data_version. Przez join_event 6k zapisów
trwałoby minuty (każdy zapis przeładowuje indeks zapisów).

Budżety (TASK_SPEC M4-07): match_for_event < 20 ms, recommend_events < 50 ms — mierzone na
rozgrzanym snapshocie (tak działa aplikacja: snapshot w RAM, przeładowanie tylko po zapisie).
"""

from __future__ import annotations

import random
import sqlite3
import statistics
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from shared.models import INTEREST_TAGS, Attendance, AttendanceStatus, Category, Event, User
from shared.storage import Storage

N_EVENTS = 500
N_USERS = 200
MAX_ATTENDEES = 25             # na event losowo 0..25 osób → średnio ~12, łącznie ~6k zapisów
BUDGET_MS = {
    "match_for_event": 20.0, "recommend_events": 50.0, "match_users": 50.0,
    "match_for_event+bio": 20.0, "match_users+bio": 50.0,
    "match_users+bio (zimny cache)": 50.0,           # M4-08: „brak wpływu na czas reruna > 50 ms”
}


BIO_FRAGMENTS = [
    "Od niedawna w Krakowie", "szukam ludzi na koncerty", "kocham jazz i winyle", "biegam rano po Błoniach",
    "programistka Pythona", "fotografuję miasto nocą", "chodzę do teatru co tydzień", "gram w planszówki",
    "uczę się hiszpańskiego", "lubię dobre wino", "fan sci-fi i gier", "chodzę po górach w weekendy",
    "studentka architektury", "techno do rana", "opera i muzyka klasyczna", "street food i kawa speciality",
    "Erasmus student, love history", "joga i medytacja", "stand-up i kino", "startupowiec, networking",
]


def build_benchmark_storage(path: str | Path, *, seed: int = 42, now: datetime | None = None) -> Storage:
    rng = random.Random(seed)
    bio_rng = random.Random(seed + 1)                    # osobny strumień: bio nie zmienia reszty danych
    now = now or datetime.now()
    store = Storage(path, seed_if_empty=False)

    users = [User(id=f"u_{i:03d}", name=f"Osoba {i:03d}", tags=rng.sample(INTEREST_TAGS, rng.randint(3, 7)),
                  bio=", ".join(bio_rng.sample(BIO_FRAGMENTS, bio_rng.randint(2, 4))) + ".")
             for i in range(N_USERS)]
    for user in users:
        store.upsert_user(user)
    categories = list(Category)
    store.upsert_events(
        Event(id=f"e_{i:03d}", title=f"Event {i:03d}", category=rng.choice(categories),
              tags=rng.sample(INTEREST_TAGS, rng.randint(0, 3)),
              start=now + timedelta(days=rng.uniform(-10, 40)), venue="X", lat=50.06, lon=19.93)
        for i in range(N_EVENTS)
    )

    rows = []
    for i in range(N_EVENTS):
        for user in rng.sample(users, rng.randint(0, MAX_ATTENDEES)):
            att = Attendance(
                user_id=user.id, event_id=f"e_{i:03d}",
                status=AttendanceStatus.INTERESTED if rng.random() < 0.2 else AttendanceStatus.GOING,
                open_to_meet=rng.random() >= 0.1,
            )
            rows.append((att.user_id, att.event_id, att.model_dump_json()))
    with sqlite3.connect(path) as conn:                  # „inny proces” — patrz docstring modułu
        conn.executemany("INSERT INTO attendance (user_id, event_id, data) VALUES (?, ?, ?)", rows)
    store.invalidate_cache()
    return store


def time_ms(fn: Callable[[], object], *, repeat: int = 7) -> float:
    """Mediana czasu wywołania w ms; pierwsze (rozgrzewka snapshotu) nie jest liczone."""
    fn()
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def worst_cases(store: Storage) -> tuple[User, str]:
    """Najbardziej aktywna osoba (najwięcej zapisów) i najliczniejszy event — najdroższe wywołania."""
    user = max(store.list_users(), key=lambda u: (len(store.list_user_attendance(u.id)), u.id))
    event_id = max((e.id for e in store.list_events()), key=lambda eid: (len(store.list_attendees(eid)), eid))
    return user, event_id


def run(store: Storage) -> dict[str, float]:
    from m4_matching.bio import _tfidf_vectors
    from m4_matching.engine import WEIGHTS, match_for_event, match_users, recommend_events

    user, event_id = worst_cases(store)
    bio_on = {**WEIGHTS, "bio": 0.10}

    def cold_bio_ms() -> float:                      # pierwsze wywołanie po zmianie bio (pusty cache)
        _tfidf_vectors.cache_clear()
        start = time.perf_counter()
        match_users(store, user, weights=bio_on)
        return (time.perf_counter() - start) * 1000

    return {
        "match_for_event": time_ms(lambda: match_for_event(store, user, event_id)),
        "recommend_events": time_ms(lambda: recommend_events(store, user)),
        "match_users": time_ms(lambda: match_users(store, user)),
        "match_for_event+bio": time_ms(lambda: match_for_event(store, user, event_id, weights=bio_on)),
        "match_users+bio": time_ms(lambda: match_users(store, user, weights=bio_on)),
        "match_users+bio (zimny cache)": statistics.median(cold_bio_ms() for _ in range(5)),
    }


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.perf_counter()
        bench = build_benchmark_storage(Path(tmp) / "bench.db")
        stats = bench.stats()
        print(f"dane: {stats['events']} eventów, {stats['users']} osób, {stats['attendance']} zapisów "
              f"({(time.perf_counter() - t0):.1f} s)")
        for name, ms in run(bench).items():
            print(f"{name:<30} {ms:7.2f} ms   (budżet {BUDGET_MS[name]:.0f} ms)")
        bench.close()
