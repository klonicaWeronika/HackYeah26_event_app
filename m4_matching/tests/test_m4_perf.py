"""M4-07 — benchmark 500 eventów × 200 osób (time.perf_counter, mediana z 7 wywołań).

Mierzymy najdroższe przypadki: najbardziej aktywną osobę i najliczniejszy event.
Szczegóły i ręczny podgląd czasów: python -m m4_matching.benchmark
"""

from __future__ import annotations

import pytest

from m4_matching.benchmark import (
    BUDGET_MS,
    N_EVENTS,
    N_USERS,
    build_benchmark_storage,
    time_ms,
    worst_cases,
)
from m4_matching.engine import build_idf, match_for_event, match_users, recommend_events
from shared.models import User
from shared.storage import Storage


@pytest.fixture(scope="module")
def bench(tmp_path_factory) -> Storage:
    store = build_benchmark_storage(tmp_path_factory.mktemp("m4_bench") / "bench.db")
    yield store
    store.close()


@pytest.fixture(scope="module")
def worst(bench: Storage) -> tuple[User, str]:
    return worst_cases(bench)


def test_benchmark_data_has_expected_scale(bench: Storage, worst: tuple[User, str]):
    stats = bench.stats()
    assert stats["events"] == N_EVENTS and stats["users"] == N_USERS
    assert stats["attendance"] > 5_000
    user, event_id = worst
    assert len(bench.list_user_attendance(user.id)) >= 40              # sporo wspólnych eventów do policzenia
    assert len(bench.list_attendees(event_id)) >= 20


def test_match_for_event_within_budget(bench: Storage, worst: tuple[User, str]):
    user, event_id = worst
    assert match_for_event(bench, user, event_id)                     # benchmark liczy prawdziwą pracę
    assert time_ms(lambda: match_for_event(bench, user, event_id)) < BUDGET_MS["match_for_event"]


def test_recommend_events_within_budget(bench: Storage, worst: tuple[User, str]):
    user, _ = worst
    assert len(recommend_events(bench, user)) == 5
    assert time_ms(lambda: recommend_events(bench, user)) < BUDGET_MS["recommend_events"]


def test_match_users_within_budget(bench: Storage, worst: tuple[User, str]):
    user, _ = worst
    assert match_users(bench, user)
    assert time_ms(lambda: match_users(bench, user)) < BUDGET_MS["match_users"]


def test_idf_is_cheap_enough_to_skip_caching(bench: Storage):
    """IDF liczymy raz na wywołanie (nie na parę osób). Przy 200 osobach to ~0.2 ms, więc cache
    po wersji danych nie jest potrzebny — ten test pilnuje, czy to założenie nadal obowiązuje."""
    assert time_ms(lambda: build_idf(bench.list_users())) < 2.0
