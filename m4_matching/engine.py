"""
M4 — silnik matchingu i rekomendacji. CZYSTA LOGIKA: zero importów streamlit.

Zakres: m4_matching/TASK_SPEC.md
Publiczne API (kontrakt — sygnatur nie zmieniamy bez PR; wolno dodawać argumenty opcjonalne):
    tag_similarity(a, b, *, idf=None) -> (score, shared_tags)
    match_for_event(storage, user, event_id, *, limit=10, weights=None) -> list[MatchResult]
    recommend_events(storage, user, *, limit=5) -> list[Recommendation]
Pomocnicze (nowe):
    build_idf(users) -> IdfWeights
    match_breakdown(storage, user, event_id, *, weights=None) -> list[MatchBreakdown]  (sandbox, M4-03)

Model scoringu:
    score = Σ wᵢ·sᵢ / Σ wᵢ   (po sygnałach obecnych w danym kontekście), przycięte do [0, 1].
    Sygnały są znormalizowane do [0, 1]; wagi w WEIGHTS poniżej.
    Sygnały dopasowania na evencie:
      tags           Jaccard ważony IDF profili (M4-01)
      co_attendance  min(n / 3, 1); n = inne wspólne wydarzenia (przeszłe i nadchodzące), na których
                     OBOJE mają open_to_meet=True — ukryty zapis nie wycieka przez licznik
      event_fit      |tagi osoby ∩ tagi eventu| / |tagi eventu|; event bez tagów → sygnału brak
                     (nie 0), więc słabo otagowane eventy ze scrapera nie zaniżają procentów
      status         GOING = 1.0, INTERESTED = 0.5

Determinizm (ten sam stan danych → ten sam wynik i kolejność):
    * sumy liczymy przez math.fsum — wynik nie zależy od kolejności iteracji po zbiorach
      (a ta zależy od PYTHONHASHSEED),
    * remisy rozstrzygamy alfabetycznie: (−score, imię, id) / (−score, start, id).
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from shared.models import AttendanceStatus, MatchResult, Recommendation, User, normalize_tag
from shared.storage import Storage

# --------------------------------------------------------------------------- #
# Wagi — JEDYNE miejsce strojenia (sandbox: streamlit run m4_matching/sandbox.py)
# --------------------------------------------------------------------------- #

WEIGHTS: dict[str, float] = {
    "tags": 0.60,            # podobieństwo profili — Jaccard ważony IDF (dominuje: plan B ze speców)
    "co_attendance": 0.20,   # inne wspólne wydarzenia
    "event_fit": 0.10,       # zainteresowania osoby pasują do tego eventu (> 0.12 → Kuba wyprzedza
                             # Natalię na e_jazz_alchemia i psuje scenariusz demo)
    "status": 0.10,          # GOING > INTERESTED
}

CO_ATTENDANCE_SATURATION = 3                 # tyle wspólnych wydarzeń daje pełny sygnał co_attendance
STATUS_VALUE: dict[AttendanceStatus, float] = {
    AttendanceStatus.GOING: 1.0,
    AttendanceStatus.INTERESTED: 0.5,
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


@dataclass(frozen=True)
class MatchBreakdown:
    """Dopasowanie z rozbiciem na sygnały — do sandboxa i do budowy uzasadnień (M4-03)."""

    user: User
    score: float                             # zaokrąglony jak w MatchResult
    signals: Mapping[str, float]             # sygnały w [0, 1] PRZED ważeniem (brak klucza = brak sygnału)
    shared_tags: tuple[str, ...]             # wspólne tagi profili, od najrzadszego
    co_event_ids: tuple[str, ...]            # inne wspólne wydarzenia (oboje open_to_meet), posortowane
    event_fit_tags: tuple[str, ...]          # tagi osoby, które ma też event
    status: AttendanceStatus


def _shared_events(storage: Storage, user_id: str, exclude_event_id: str) -> dict[str, tuple[str, ...]]:
    """{inny user_id: wspólne wydarzenia} — tylko tam, gdzie OBOJE mają open_to_meet=True.

    Symetryczne (A→B == B→A) i nie zdradza ukrytych zapisów żadnej ze stron.
    """
    shared: dict[str, list[str]] = defaultdict(list)
    for mine in storage.list_user_attendance(user_id):
        if mine.event_id == exclude_event_id or not mine.open_to_meet:
            continue
        for theirs in storage.list_attendees(mine.event_id):
            if theirs.user_id != user_id and theirs.open_to_meet:
                shared[theirs.user_id].append(mine.event_id)
    return {uid: tuple(sorted(ids)) for uid, ids in shared.items()}


def _breakdown_sort_key(b: MatchBreakdown) -> tuple:
    return (-b.score, b.user.name.casefold(), b.user.id)


def match_breakdown(
    storage: Storage, user: User, event_id: str, *, weights: Mapping[str, float] | None = None
) -> list[MatchBreakdown]:
    """Wszystkie widoczne osoby z eventu (bez `user`, tylko open_to_meet) z rozbiciem score."""
    attendances = [
        a for a in storage.list_attendees(event_id)
        if a.user_id != user.id and a.open_to_meet
    ]
    if not attendances:
        return []
    others = storage.get_users(a.user_id for a in attendances)
    idf = build_idf(storage.list_users())            # raz na wywołanie (~µs dla setek osób)
    co_events = _shared_events(storage, user.id, event_id)
    event = storage.get_event(event_id)
    event_tags = set(event.tags) if event else set()

    results: list[MatchBreakdown] = []
    for att in attendances:
        other = others.get(att.user_id)
        if other is None:                            # zapis osoby usuniętej z bazy
            continue
        tags_sim, shared = tag_similarity(user.tags, other.tags, idf=idf)
        co = co_events.get(other.id, ())
        signals = {
            "tags": tags_sim,
            "co_attendance": min(len(co) / CO_ATTENDANCE_SATURATION, 1.0),
            "status": STATUS_VALUE.get(att.status, 0.0),
        }
        fit_tags = tuple(t for t in other.tags if t in event_tags)
        if event_tags:
            signals["event_fit"] = len(fit_tags) / len(event_tags)
        results.append(MatchBreakdown(
            user=other,
            score=round(weighted_score(signals, weights), SCORE_DECIMALS),
            signals=signals,
            shared_tags=tuple(shared),
            co_event_ids=co,
            event_fit_tags=fit_tags,
            status=att.status,
        ))
    results.sort(key=_breakdown_sort_key)
    return results


def match_for_event(
    storage: Storage, user: User, event_id: str, *, limit: int = 10,
    weights: Mapping[str, float] | None = None,
) -> list[MatchResult]:
    """Osoby zapisane na event (bez `user`, tylko open_to_meet), od najlepiej dopasowanej.

    `weights` — opcjonalne nadpisanie WEIGHTS (sandbox); domyślnie WEIGHTS.
    """
    return [
        MatchResult(
            user=b.user, event_id=event_id, score=b.score,
            shared_tags=list(b.shared_tags), reason=match_reason(b),
        )
        for b in match_breakdown(storage, user, event_id, weights=weights)[:limit]
    ]


def match_reason(b: MatchBreakdown) -> str:
    """Krótkie uzasadnienie do UI (M4-03 rozbuduje o współobecność i limit 60 znaków)."""
    return _reason(list(b.shared_tags))


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
