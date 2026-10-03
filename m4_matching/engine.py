"""
M4 — silnik matchingu i rekomendacji. CZYSTA LOGIKA: zero importów streamlit.

Zakres: m4_matching/TASK_SPEC.md
Publiczne API (kontrakt — sygnatur nie zmieniamy bez PR; wolno dodawać argumenty opcjonalne):
    tag_similarity(a, b, *, idf=None) -> (score, shared_tags)
    match_for_event(storage, user, event_id, *, limit=10) -> list[MatchResult]
    recommend_events(storage, user, *, limit=5) -> list[Recommendation]
Pomocnicze (nowe):
    build_idf(users) -> IdfWeights

Model scoringu:
    score = Σ wᵢ·sᵢ / Σ wᵢ   (po sygnałach obecnych w danym kontekście), przycięte do [0, 1].
    Sygnały są znormalizowane do [0, 1]; wagi w WEIGHTS poniżej.

Determinizm (ten sam stan danych → ten sam wynik i kolejność):
    * sumy liczymy przez math.fsum — wynik nie zależy od kolejności iteracji po zbiorach
      (a ta zależy od PYTHONHASHSEED),
    * remisy rozstrzygamy alfabetycznie: (−score, imię, id) / (−score, start, id).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from shared.models import MatchResult, Recommendation, User, normalize_tag
from shared.storage import Storage

# --------------------------------------------------------------------------- #
# Wagi — JEDYNE miejsce strojenia (sandbox: streamlit run m4_matching/sandbox.py)
# --------------------------------------------------------------------------- #

WEIGHTS: dict[str, float] = {
    "tags": 0.60,            # M4-01: podobieństwo profili — Jaccard ważony IDF
    # M4-02: "co_attendance", "event_fit", "status"
}

SCORE_DECIMALS = 3          # precyzja score w MatchResult/Recommendation (i w porównaniu remisów)


# --------------------------------------------------------------------------- #
# IDF po tagach użytkowników
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IdfWeights:
    """idf(t) = ln((N + 1) / (df(t) + 1)) + 1 — rzadki tag waży więcej niż popularny.

    Tag nieznany (df = 0) dostaje maksymalną wagę ln(N + 1) + 1, nigdy 0 ani wartość ujemną.
    """

    n_users: int
    df: Mapping[str, int] = field(default_factory=dict)

    def __call__(self, tag: str) -> float:
        return math.log((self.n_users + 1) / (self.df.get(tag, 0) + 1)) + 1.0


def build_idf(users: Iterable[User]) -> IdfWeights:
    """Liczy df po tagach wszystkich użytkowników (każdy tag liczony raz na osobę)."""
    df: Counter[str] = Counter()
    n_users = 0
    for user in users:
        n_users += 1
        df.update(set(user.tags))
    return IdfWeights(n_users=n_users, df=dict(df))


# --------------------------------------------------------------------------- #
# Sygnały i łączenie
# --------------------------------------------------------------------------- #


def _unique_tags(tags: Iterable[str]) -> list[str]:
    """Normalizacja jak w modelach + usunięcie duplikatów z zachowaniem kolejności."""
    return list(dict.fromkeys(t for t in (normalize_tag(str(raw)) for raw in tags) if t))


def tag_similarity(
    a: list[str], b: list[str], *, idf: Callable[[str], float] | None = None
) -> tuple[float, list[str]]:
    """Jaccard ważony: Σ w(A∩B) / Σ w(A∪B) + lista wspólnych tagów.

    * `idf=None` → w(t) = 1, czyli klasyczny Jaccard |A∩B| / |A∪B| (zgodność wstecz);
      wspólne tagi w kolejności jak w `a`.
    * `idf` podane (np. `build_idf(storage.list_users())`) → rzadkie wspólne tagi ważą więcej;
      wspólne tagi od najrzadszego (najbardziej mówiącego), remis → kolejność w `a`.
    Wynik zawsze w [0, 1] i symetryczny względem (a, b).
    """
    tags_a, tags_b = _unique_tags(a), _unique_tags(b)
    set_b = set(tags_b)
    union = set(tags_a) | set_b
    if not union:
        return 0.0, []
    shared = [t for t in tags_a if t in set_b]
    weight = idf or (lambda _tag: 1.0)
    score = math.fsum(weight(t) for t in shared) / math.fsum(weight(t) for t in union)
    if idf is not None:
        position = {t: i for i, t in enumerate(tags_a)}
        shared.sort(key=lambda t: (-weight(t), position[t]))
    return _clip(score), shared


def _clip(value: float) -> float:
    return min(1.0, max(0.0, value))


def weighted_score(signals: Mapping[str, float], weights: Mapping[str, float] | None = None) -> float:
    """Σ wᵢ·sᵢ / Σ wᵢ po sygnałach obecnych w `signals` (brak sygnału ≠ sygnał równy 0).

    Sygnały z wagą 0 albo spoza `weights` są ignorowane. Brak dodatnich wag → 0.
    """
    weights = WEIGHTS if weights is None else weights
    active = sorted(k for k in signals if weights.get(k, 0.0) > 0)
    total = math.fsum(weights[k] for k in active)
    if total <= 0:
        return 0.0
    return _clip(math.fsum(weights[k] * _clip(signals[k]) for k in active) / total)


# --------------------------------------------------------------------------- #
# Dopasowania na evencie
# --------------------------------------------------------------------------- #


def _reason(shared: list[str]) -> str:
    if not shared:
        return "Idziecie na to samo wydarzenie"
    return "Oboje lubicie: " + ", ".join(shared[:3])


def _match_sort_key(match: MatchResult) -> tuple:
    return (-match.score, match.user.name.casefold(), match.user.id)


def match_for_event(storage: Storage, user: User, event_id: str, *, limit: int = 10) -> list[MatchResult]:
    """Osoby zapisane na event (bez `user`, tylko open_to_meet), od najlepiej dopasowanej."""
    attendee_ids = [
        a.user_id for a in storage.list_attendees(event_id)
        if a.user_id != user.id and a.open_to_meet
    ]
    if not attendee_ids:
        return []
    idf = build_idf(storage.list_users())       # raz na wywołanie (~µs dla setek osób)
    results: list[MatchResult] = []
    for other in storage.get_users(attendee_ids).values():
        tags_sim, shared = tag_similarity(user.tags, other.tags, idf=idf)
        score = weighted_score({"tags": tags_sim})
        results.append(MatchResult(
            user=other, event_id=event_id, score=round(score, SCORE_DECIMALS),
            shared_tags=shared, reason=_reason(shared),
        ))
    results.sort(key=_match_sort_key)
    return results[:limit]


# --------------------------------------------------------------------------- #
# Rekomendacje
# --------------------------------------------------------------------------- #


def recommend_events(storage: Storage, user: User, *, limit: int = 5) -> list[Recommendation]:
    """Nadchodzące eventy, na które user się jeszcze nie zapisał, ranking po wspólnych tagach."""
    joined = {a.event_id for a in storage.list_user_attendance(user.id)}
    now = datetime.now()
    user_tags = set(user.tags)
    recs: list[Recommendation] = []
    for event in storage.list_events():
        if event.id in joined or event.end_or_start < now:
            continue
        shared = [t for t in event.tags if t in user_tags]
        if not shared:
            continue
        score = len(shared) / max(len(event.tags), 1)
        recs.append(Recommendation(
            event=event, score=round(score, SCORE_DECIMALS), reason="Pasuje do: " + ", ".join(shared),
        ))
    recs.sort(key=lambda r: (-r.score, r.event.start, r.event.id))
    return recs[:limit]


if __name__ == "__main__":  # python -m m4_matching.engine  — szybki podgląd na mockach
    from shared.mock_data import DEMO_USER_ID

    store = Storage(":memory:")
    me = store.get_user(DEMO_USER_ID)
    assert me is not None
    for m in match_for_event(store, me, "e_jazz_alchemia"):
        print(f"{m.score:.3f}  {m.user.name:<8} {m.reason}")
    print("---")
    for r in recommend_events(store, me):
        print(f"{r.score:.3f}  {r.event.title}  ({r.reason})")
