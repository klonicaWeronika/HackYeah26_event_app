"""M4-01 — scoring v1: Dice ważony IDF, pierwotnie Jaccard (zakres, monotoniczność, determinizm, tie-break)."""

from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from m4_matching.engine import (
    IdfWeights,
    build_idf,
    match_breakdown,
    match_for_event,
    recommend_breakdown,
    recommend_events,
    tag_similarity,
    weighted_score,
)
from shared.models import INTEREST_TAGS, Event, User
from shared.storage import Storage

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def idf(storage: Storage) -> IdfWeights:
    return build_idf(storage.list_users())


def _score_of(storage: Storage, user: User, event_id: str, other_id: str) -> float:
    return next(m.score for m in match_for_event(storage, user, event_id) if m.user.id == other_id)


# --- IDF ----------------------------------------------------------------- #

def test_idf_formula_rare_tags_weigh_more(idf: IdfWeights):
    n = 12                                                    # persony w mockach
    assert idf.n_users == n
    assert idf("opera") == pytest.approx(math.log((n + 1) / (1 + 1)) + 1)      # df = 1 (Ania)
    assert idf("kino") == pytest.approx(math.log((n + 1) / (3 + 1)) + 1)       # df = 3
    assert idf("opera") > idf("kino") > 1.0
    assert idf("tag-spoza-profili") == pytest.approx(math.log(n + 1) + 1)      # df = 0 → maks.
    assert build_idf([])("cokolwiek") == pytest.approx(1.0)                    # pusta baza nie wybucha


def test_rare_shared_tag_beats_popular_one(idf: IdfWeights):
    me = ["opera", "kino"]
    rare, _ = tag_similarity(me, ["opera", "x-nieznany-1"], idf=idf)
    popular, _ = tag_similarity(me, ["kino", "x-nieznany-2"], idf=idf)
    assert rare > popular
    # bez IDF oba przypadki są nie do odróżnienia (klasyczny Dice)
    assert tag_similarity(me, ["opera", "x1"])[0] == tag_similarity(me, ["kino", "x2"])[0]


@pytest.mark.parametrize(("shared", "expected"), [(0, 0.0), (1, 0.2), (2, 0.4), (3, 0.6), (4, 0.8), (5, 1.0)])
def test_dice_scale_for_typical_profiles(shared: int, expected: float):
    """Profile po 5 tagów: k wspólnych → 2k / 10 (Jaccard dawał 0.11 / 0.25 / 0.43 dla k = 1 / 2 / 3)."""
    a = ["a", "b", "c", "d", "e"]
    b = a[:shared] + ["v", "w", "x", "y", "z"][: 5 - shared]
    assert tag_similarity(a, b)[0] == pytest.approx(expected)


def test_dice_keeps_jaccard_order(idf: IdfWeights):
    """Dice = 2J / (1 + J) — rosnąca funkcja Jaccarda, więc ranking po samych tagach się nie zmienia."""
    rnd = random.Random(7)
    pool = INTEREST_TAGS + ["x-nieznany-1"]
    for _ in range(200):
        a, b = rnd.sample(pool, rnd.randint(1, 6)), rnd.sample(pool, rnd.randint(1, 6))
        union, inter = set(a) | set(b), set(a) & set(b)
        jaccard = math.fsum(map(idf, inter)) / math.fsum(map(idf, union))
        assert tag_similarity(a, b, idf=idf)[0] == pytest.approx(2 * jaccard / (1 + jaccard))


# --- tag_similarity: zakres, symetria, normalizacja ----------------------- #

def test_tag_similarity_range_and_symmetry(idf: IdfWeights):
    rnd = random.Random(2026)
    pool = INTEREST_TAGS + ["x-nieznany-1", "x-nieznany-2"]
    for _ in range(300):
        a = rnd.sample(pool, rnd.randint(0, 6))
        b = rnd.sample(pool, rnd.randint(0, 6))
        for weights in (idf, None):
            ab, _ = tag_similarity(a, b, idf=weights)
            ba, _ = tag_similarity(b, a, idf=weights)
            assert 0.0 <= ab <= 1.0
            assert ab == ba                                   # fsum → dokładnie równe
    assert tag_similarity(["jazz", "kino"], ["kino", "jazz"], idf=idf)[0] == 1.0
    assert tag_similarity(["jazz"], ["opera"], idf=idf) == (0.0, [])
    assert tag_similarity([], [], idf=idf) == (0.0, [])
    assert tag_similarity(["jazz"], [], idf=idf) == (0.0, [])


def test_tag_similarity_normalizes_and_deduplicates():
    # Szkielet zwracał tu 2.0 (duplikaty w `a` liczone podwójnie).
    assert tag_similarity(["Jazz", "jazz", " #JAZZ "], ["jazz"]) == (1.0, ["jazz"])


def test_shared_tags_rarest_first(storage: Storage, demo_user: User, idf: IdfWeights):
    bartek = storage.get_user("u_bartek")
    _, shared = tag_similarity(demo_user.tags, bartek.tags, idf=idf)
    assert set(shared) == {"jazz", "fotografia"}
    assert [idf(t) for t in shared] == sorted((idf(t) for t in shared), reverse=True)
    # bez IDF — kolejność jak w profilu `a` (zachowanie szkieletu)
    assert tag_similarity(demo_user.tags, bartek.tags)[1] == [t for t in demo_user.tags if t in bartek.tags]


# --- monotoniczność ------------------------------------------------------ #

def test_more_shared_tags_never_lower_score(demo_user: User, idf: IdfWeights):
    other: list[str] = ["piłka nożna"]
    previous, _ = tag_similarity(demo_user.tags, other, idf=idf)
    for tag in demo_user.tags:                                # zamieniamy „cudze” tagi we wspólne
        other.append(tag)
        current, _ = tag_similarity(demo_user.tags, other, idf=idf)
        assert current > previous
        previous = current
    # nowy tag dodany OBU stronom też nie obniża wyniku
    before, _ = tag_similarity(["jazz", "kino"], ["jazz", "rock"], idf=idf)
    after, _ = tag_similarity(["jazz", "kino", "opera"], ["jazz", "rock", "opera"], idf=idf)
    assert after >= before


def test_profile_edit_with_shared_tags_never_lowers_match(storage: Storage, demo_user: User):
    """Przez Storage: IDF przelicza się po zmianie profilu, a wynik i tak nie spada."""
    tomek = storage.get_user("u_tomek")
    scores = [_score_of(storage, demo_user, "e_jazz_alchemia", "u_tomek")]
    for tag in [t for t in demo_user.tags if t not in tomek.tags]:
        tomek = storage.upsert_user(tomek.copy_with(tags=tomek.tags + [tag]))
        scores.append(_score_of(storage, demo_user, "e_jazz_alchemia", "u_tomek"))
    assert scores == sorted(scores) and scores[-1] > scores[0]


# --- match_for_event ----------------------------------------------------- #

def test_tags_signal_is_idf_dice(storage: Storage, demo_user: User, idf: IdfWeights):
    breakdown = match_breakdown(storage, demo_user, "e_jazz_alchemia")
    matches = match_for_event(storage, demo_user, "e_jazz_alchemia")
    for b, m in zip(breakdown, matches, strict=True):
        expected, shared = tag_similarity(demo_user.tags, b.user.tags, idf=idf)
        assert b.signals["tags"] == expected
        assert m.user.id == b.user.id and m.shared_tags == shared
    # sam sygnał tagów: dwa wspólne tagi (Bartek, Natalia) > jeden (Kuba, Tomek)
    tags_only = [m.user.id for m in match_for_event(storage, demo_user, "e_jazz_alchemia",
                                                     weights={"tags": 1.0})]
    assert set(tags_only[:2]) == {"u_bartek", "u_natalia"}
    assert set(tags_only[2:]) == {"u_kuba", "u_tomek"}


def test_ties_are_broken_alphabetically(empty_storage: Storage):
    start = datetime.now() + timedelta(days=1)
    empty_storage.upsert_event(Event(id="e_t", title="T", start=start, venue="X", lat=50.06, lon=19.93))
    me = empty_storage.upsert_user(User(id="u_me", name="Ja", tags=["jazz", "kino"]))
    for uid, name in [("u_3", "Zenon"), ("u_1", "adam"), ("u_2", "Ewa"), ("u_0", "Ewa")]:
        empty_storage.upsert_user(User(id=uid, name=name, tags=["jazz", "rock"]))
        empty_storage.join_event(uid, "e_t")
    matches = match_for_event(empty_storage, me, "e_t")
    assert len({m.score for m in matches}) == 1
    assert [m.user.id for m in matches] == ["u_1", "u_0", "u_2", "u_3"]   # adam, Ewa(u_0), Ewa(u_2), Zenon


def _all_rankings(store: Storage) -> list[tuple]:
    return [
        (u.id, e.id, [(m.user.id, m.score, tuple(m.shared_tags), m.reason)
                      for m in match_for_event(store, u, e.id, limit=50)])
        for u in store.list_users() for e in store.list_events()
    ]


def test_matching_is_deterministic_across_storages():
    first, second = Storage(":memory:"), Storage(":memory:")
    try:
        assert _all_rankings(first) == _all_rankings(second)
    finally:
        first.close()
        second.close()


_RANKING_SNIPPET = """
import json
from m4_matching.engine import match_for_event
from shared.storage import Storage
s = Storage(":memory:")
print(json.dumps({f"{u.id}@{e.id}": [[m.user.id, m.score, m.shared_tags]
                  for m in match_for_event(s, u, e.id, limit=50)]
                  for u in s.list_users() for e in s.list_events()}, sort_keys=True))
"""


def test_ranking_does_not_depend_on_hash_seed():
    """Kolejność iteracji po zbiorach zależy od PYTHONHASHSEED — wynik nie może."""
    outputs = []
    for seed in ("0", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": seed,
               "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO_ROOT), os.environ.get("PYTHONPATH")]))}
        proc = subprocess.run([sys.executable, "-c", _RANKING_SNIPPET], cwd=REPO_ROOT, env=env,
                              capture_output=True, text=True, timeout=60, check=False)
        assert proc.returncode == 0, proc.stderr
        outputs.append(json.loads(proc.stdout))
    assert outputs[0] == outputs[1]


# --- weighted_score ------------------------------------------------------ #

def test_weighted_score_normalizes_by_present_signals():
    weights = {"a": 0.6, "b": 0.2, "c": 0.0}
    assert weighted_score({"a": 0.5}, weights) == pytest.approx(0.5)            # brak „b” ≠ b = 0
    assert weighted_score({"a": 1.0, "b": 0.0}, weights) == pytest.approx(0.75)
    assert weighted_score({"a": 1.0, "c": 0.0}, weights) == pytest.approx(1.0)  # waga 0 ignorowana
    assert weighted_score({"a": 7.0, "b": -3.0}, weights) == pytest.approx(0.75)  # sygnały przycięte
    assert weighted_score({"zzz": 1.0}, weights) == 0.0
    assert weighted_score({"tags": 0.4}) == pytest.approx(0.4)                  # domyślne WEIGHTS


# --- rekomendacje: deterministyczny tie-break ---------------------------- #

def test_recommendations_have_deterministic_order(storage: Storage, demo_user: User):
    """Ranking kandydatów: (−score, start, id); różnorodność (M4-05) tylko go przestawia, deterministycznie."""
    now = datetime.now()
    keys = [(-r.score, r.event.start, r.event.id) for r in recommend_breakdown(storage, demo_user, now=now)]
    assert keys == sorted(keys)
    first = recommend_events(storage, demo_user, limit=50, now=now)
    assert first == recommend_events(storage, demo_user, limit=50, now=now)
