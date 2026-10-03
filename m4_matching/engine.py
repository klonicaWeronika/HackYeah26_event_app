"""
M4 — silnik matchingu i rekomendacji. CZYSTA LOGIKA: zero importów streamlit.

Zakres: m4_matching/TASK_SPEC.md
Publiczne API (kontrakt — sygnatur nie zmieniamy bez PR; wolno dodawać argumenty opcjonalne):
    tag_similarity(a, b, *, idf=None) -> (score, shared_tags)
    match_for_event(storage, user, event_id, *, limit=10, weights=None) -> list[MatchResult]
    recommend_events(storage, user, *, limit=5) -> list[Recommendation]
    match_users(storage, user, *, limit=10) -> list[MatchResult]   (M4-06, event_id=None)
Pomocnicze (nowe):
    build_idf(users) -> IdfWeights
    match_breakdown(storage, user, event_id, *, weights=None) -> list[MatchBreakdown]  (sandbox, M4-03)
    match_reason(breakdown) -> str            uzasadnienie PL ≤ 60 znaków (M4-03)
    plural_pl(n, one, few, many) -> str       odmiana rzeczownika po liczebniku
    recommend_breakdown(storage, user, *, weights=None, now=None) -> list[RecBreakdown]  (sandbox, M4-05)

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
    Rekomendacje (REC_WEIGHTS), potem × kara za termin i reguła max 2 eventów z kategorii:
      tags           |tagi usera ∩ tagi eventu| / |tagi eventu|; event bez tagów → sygnału brak
      social         min(Σ podobieństw widocznych uczestników ze wspólnym tagiem / 0.5, 1)

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

from shared.models import AttendanceStatus, Event, MatchResult, Recommendation, User, normalize_tag
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

# Rekomendacje (M4-05): score = weighted_score(sygnały, REC_WEIGHTS) × kara za termin
REC_WEIGHTS: dict[str, float] = {
    "tags": 0.60,            # |tagi usera ∩ tagi eventu| / |tagi eventu|
    "social": 0.40,          # podobne osoby (wspólny tag) idą: min(Σ podobieństw / REC_SOCIAL_SATURATION, 1)
}
REC_SOCIAL_SATURATION = 0.5     # ≈ dwie mocno podobne osoby (podobieństwo IDF ~0.25) → pełny sygnał
REC_TIME_PENALTY = 0.30         # event za ≥ REC_TIME_HORIZON_DAYS dni traci 30% score (liniowo od dziś)
REC_TIME_HORIZON_DAYS = 14
REC_MAX_PER_CATEGORY = 2        # różnorodność: max tyle eventów jednej kategorii w top `limit`


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
    co_past_count: int = 0                   # ile z co_event_ids już się odbyło (do uzasadnienia)


def _shared_events(
    storage: Storage, user_id: str, exclude_event_id: str | None,
) -> dict[str, tuple[str, ...]]:
    """{inny user_id: wspólne wydarzenia} — tylko tam, gdzie OBOJE mają open_to_meet=True.

    Symetryczne (A→B == B→A) i nie zdradza ukrytych zapisów żadnej ze stron.
    `exclude_event_id` — bieżący event, który się nie liczy (None: liczą się wszystkie).
    """
    shared: dict[str, list[str]] = defaultdict(list)
    for mine in storage.list_user_attendance(user_id):
        if mine.event_id == exclude_event_id or not mine.open_to_meet:
            continue
        for theirs in storage.list_attendees(mine.event_id):
            if theirs.user_id != user_id and theirs.open_to_meet:
                shared[theirs.user_id].append(mine.event_id)
    return {uid: tuple(sorted(ids)) for uid, ids in shared.items()}


def _past_event_ids(storage: Storage, co_events: Mapping[str, tuple[str, ...]]) -> set[str]:
    """Które ze wspólnych wydarzeń już się skończyły (do „Już razem na …”)."""
    now = datetime.now()
    return {
        eid for ids in co_events.values() for eid in ids
        if (e := storage.get_event(eid)) is not None and e.end_or_start < now
    }


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
    past_ids = _past_event_ids(storage, co_events)

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
            co_past_count=sum(1 for eid in co if eid in past_ids),
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


# --------------------------------------------------------------------------- #
# Dopasowania globalne (profil / onboarding)
# --------------------------------------------------------------------------- #


def match_users(
    storage: Storage, user: User, *, limit: int = 10, weights: Mapping[str, float] | None = None,
) -> list[MatchResult]:
    """Osoby podobne do `user` niezależnie od eventu (`event_id=None`), od najlepiej dopasowanej.

    Sygnały jak w match_for_event bez kontekstu eventu: `tags` (Jaccard IDF) i `co_attendance`
    (wszystkie wspólne wydarzenia, gdzie oboje są widoczni) — event_fit i status są nieobecne,
    więc wagi normalizują się po tych dwóch. Pomijamy osoby, z którymi nic nie łączy (score 0).
    """
    others = [u for u in storage.list_users() if u.id != user.id]
    idf = build_idf(storage.list_users())
    co_events = _shared_events(storage, user.id, None)
    past_ids = _past_event_ids(storage, co_events)

    results: list[MatchResult] = []
    for other in others:
        tags_sim, shared = tag_similarity(user.tags, other.tags, idf=idf)
        co = co_events.get(other.id, ())
        if not shared and not co:
            continue
        signals = {"tags": tags_sim, "co_attendance": min(len(co) / CO_ATTENDANCE_SATURATION, 1.0)}
        co_phrase = _co_attendance_phrase(sum(1 for eid in co if eid in past_ids), len(co), also=False)
        results.append(MatchResult(
            user=other, event_id=None,
            score=round(weighted_score(signals, weights), SCORE_DECIMALS),
            shared_tags=shared,
            reason=_tags_and(shared, co_phrase) or co_phrase or "Podobne zainteresowania",
        ))
    results.sort(key=lambda m: (-m.score, m.user.name.casefold(), m.user.id))
    return results[:max(limit, 0)]


# --------------------------------------------------------------------------- #
# Uzasadnienia (PL, ≤ REASON_MAX_LEN znaków)
# --------------------------------------------------------------------------- #
#
# Formy neutralne płciowo: nie znamy płci osób, więc zamiast „Oboje lubicie” / „Byliście razem”
# piszemy „Wspólne: …” / „Już razem na …”. Czasownik w 2. os. l.mn. czasu teraźniejszego
# („Idziecie”) jest neutralny.

REASON_MAX_LEN = 60
REASON_SEP = " · "
REASON_MAX_TAGS = 3
_ELLIPSIS = "…"


def plural_pl(n: int, one: str, few: str, many: str) -> str:
    """Forma rzeczownika po liczebniku: 1 wydarzenie, 2–4 wydarzenia, 5+ wydarzeń (12–14 → many)."""
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def events_locative(n: int) -> str:
    """„1 wydarzeniu”, „2 wydarzeniach” — w miejscowniku l.mn. forma nie zależy od liczby."""
    return f"{n} {'wydarzeniu' if n == 1 else 'wydarzeniach'}"


def _tag_list(prefix: str, tags: Iterable[str], budget: int, *, truncate: bool = True) -> str | None:
    """`prefix` + tyle tagów (max REASON_MAX_TAGS), ile zmieści się w `budget` znakach.

    Gdy nie mieści się nawet pierwszy tag: `truncate` → skracamy go wielokropkiem (zostaje
    < 3 znaków → None), inaczej None.
    """
    tags = list(tags)[:REASON_MAX_TAGS]
    if not tags:
        return None
    taken: list[str] = []
    for tag in tags:
        if len(prefix) + len(", ".join([*taken, tag])) > budget:
            break
        taken.append(tag)
    if taken:
        return prefix + ", ".join(taken)
    if not truncate:
        return None
    room = budget - len(prefix) - len(_ELLIPSIS)
    return prefix + tags[0][:room].rstrip() + _ELLIPSIS if room >= 3 else None


def _co_attendance_phrase(past: int, total: int, *, also: bool = True) -> str | None:
    """Przeszłe wspólne wydarzenia mają pierwszeństwo; `also` — „też” obok bieżącego eventu."""
    if past:
        return "Już razem na " + events_locative(past)
    if total:
        return ("Razem też na " if also else "Razem na ") + events_locative(total)
    return None


def _tags_and(shared_tags: Iterable[str], extra: str | None) -> str | None:
    """„Wspólne: …” + ewentualnie „ · extra”. Tagu nie ucinamy, żeby zmieścić `extra` —
    gdy całe słowo się nie mieści, rezygnujemy z `extra`. Brak tagów → None."""
    shared_tags = tuple(shared_tags)
    if extra and (tags := _tag_list("Wspólne: ", shared_tags,
                                    REASON_MAX_LEN - len(REASON_SEP) - len(extra), truncate=False)):
        return tags + REASON_SEP + extra
    return _tag_list("Wspólne: ", shared_tags, REASON_MAX_LEN)


def _status_phrase(status: AttendanceStatus) -> str:
    if status is AttendanceStatus.INTERESTED:
        return "Też rozważa to wydarzenie"
    return "Idziecie na to samo wydarzenie"


def match_reason(b: MatchBreakdown) -> str:
    """Uzasadnienie do UI: wspólne tagi · współobecność; bez nich dopasowanie do eventu albo status.

    Zawsze niepuste i ≤ REASON_MAX_LEN znaków, np. „Wspólne: jazz, fotografia · Już razem na 2
    wydarzeniach”.
    """
    co = _co_attendance_phrase(b.co_past_count, len(b.co_event_ids))
    if b.shared_tags:
        return _tags_and(b.shared_tags, co) or _status_phrase(b.status)
    if co:
        return co
    fit = _tag_list("Pasuje do wydarzenia: ", b.event_fit_tags, REASON_MAX_LEN)
    return fit or _status_phrase(b.status)


# --------------------------------------------------------------------------- #
# Rekomendacje
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RecBreakdown:
    """Kandydat na rekomendację z rozbiciem na sygnały — do sandboxa i uzasadnień (M4-05)."""

    event: Event
    score: float                             # zaokrąglony, już z karą za termin
    signals: Mapping[str, float]             # sygnały w [0, 1] PRZED ważeniem (brak klucza = brak sygnału)
    time_factor: float                       # mnożnik kary za termin, w [1 − REC_TIME_PENALTY, 1]
    fit_tags: tuple[str, ...]                # tagi usera, które ma event (kolejność jak w evencie)
    similar_people: tuple[User, ...]         # widoczni uczestnicy ze wspólnym tagiem, od najbardziej podobnych


def _time_factor(event: Event, now: datetime) -> float:
    """1.0 dla eventu dziś/trwającego, liniowo w dół do 1 − REC_TIME_PENALTY za REC_TIME_HORIZON_DAYS dni."""
    days = max((event.start - now).total_seconds() / 86_400, 0.0)
    return 1.0 - REC_TIME_PENALTY * min(days / REC_TIME_HORIZON_DAYS, 1.0)


def recommend_breakdown(
    storage: Storage, user: User, *, weights: Mapping[str, float] | None = None,
    now: datetime | None = None,
) -> list[RecBreakdown]:
    """Wszyscy kandydaci posortowani po score — BEZ reguły różnorodności (ta jest w recommend_events).

    Kandydat: event nadchodzący lub trwający, user nie jest zapisany, a event pasuje tagami
    albo idzie na niego ktoś podobny (widoczny, ≥ 1 wspólny tag z userem).
    """
    weights = REC_WEIGHTS if weights is None else weights
    now = now or datetime.now()
    joined = {a.event_id for a in storage.list_user_attendance(user.id)}
    user_tags = set(_unique_tags(user.tags))
    candidates = [e for e in storage.list_events() if e.id not in joined and e.end_or_start >= now]
    visible = {
        e.id: [a.user_id for a in storage.list_attendees(e.id) if a.open_to_meet and a.user_id != user.id]
        for e in candidates
    }
    people = storage.get_users({uid for ids in visible.values() for uid in ids})
    idf = build_idf(storage.list_users())
    similarity = {                                    # raz na osobę, nie raz na parę (osoba, event)
        uid: tag_similarity(user.tags, person.tags, idf=idf)[0] for uid, person in people.items()
    }

    results: list[RecBreakdown] = []
    for event in candidates:
        fit_tags = tuple(t for t in event.tags if t in user_tags)
        similar = sorted(
            (people[uid] for uid in visible[event.id] if uid in people and similarity[uid] > 0),
            key=lambda p: (-similarity[p.id], p.name.casefold(), p.id),
        )
        if not fit_tags and not similar:
            continue
        signals = {"social": min(math.fsum(similarity[p.id] for p in similar) / REC_SOCIAL_SATURATION, 1.0)}
        if event.tags:                                # event bez tagów → sygnału brak (nie 0), jak event_fit
            signals["tags"] = len(fit_tags) / len(event.tags)
        factor = _time_factor(event, now)
        results.append(RecBreakdown(
            event=event,
            score=round(weighted_score(signals, weights) * factor, SCORE_DECIMALS),
            signals=signals,
            time_factor=factor,
            fit_tags=fit_tags,
            similar_people=tuple(similar),
        ))
    results.sort(key=lambda r: (-r.score, r.event.start, r.event.id))
    return results


def _diversify(ranked: list[RecBreakdown], limit: int) -> list[RecBreakdown]:
    """Zachłannie od najlepszego, max REC_MAX_PER_CATEGORY z jednej kategorii.

    Gdy różnorodnych kandydatów jest za mało, wolne miejsca dopełniamy pominiętymi (wg score) —
    lepiej 5 rekomendacji z powtórzoną kategorią niż 3.
    """
    picked: list[RecBreakdown] = []
    skipped: list[RecBreakdown] = []
    per_category: Counter = Counter()
    for r in ranked:
        if len(picked) >= limit:
            break
        if per_category[r.event.category] < REC_MAX_PER_CATEGORY:
            picked.append(r)
            per_category[r.event.category] += 1
        else:
            skipped.append(r)
    return picked + skipped[:max(limit - len(picked), 0)]


def _people_phrases(people: tuple[User, ...]) -> list[str]:
    """Warianty „kto idzie” od najdłuższego: z imionami, potem sama liczba."""
    n = len(people)
    if not n:
        return []
    names = [p.name for p in people[:2]]
    if n == 1:
        with_names = f"Idzie {names[0]}"
    elif n == 2:
        with_names = f"Idą {names[0]} i {names[1]}"
    else:
        rest = n - 2
        with_names = (f"Idą {names[0]}, {names[1]} i {rest} "
                      + plural_pl(rest, "inna osoba", "inne osoby", "innych osób"))
    count = (plural_pl(n, "Idzie", "Idą", "Idzie") + f" {n} "
             + plural_pl(n, "podobna osoba", "podobne osoby", "podobnych osób"))
    return [with_names, count]


def recommendation_reason(r: RecBreakdown) -> str:
    """„Pasuje do: kino · Idą Bartek i Ania”; zawsze niepuste i ≤ REASON_MAX_LEN znaków."""
    people = [p for p in _people_phrases(r.similar_people) if len(p) <= REASON_MAX_LEN]
    if r.fit_tags:
        for phrase in people:
            budget = REASON_MAX_LEN - len(REASON_SEP) - len(phrase)
            if tags := _tag_list("Pasuje do: ", r.fit_tags, budget, truncate=False):
                return tags + REASON_SEP + phrase
        if tags := _tag_list("Pasuje do: ", r.fit_tags, REASON_MAX_LEN):
            return tags
    return people[0] if people else "Pasuje do Twoich zainteresowań"


def recommend_events(
    storage: Storage, user: User, *, limit: int = 5, weights: Mapping[str, float] | None = None,
    now: datetime | None = None,
) -> list[Recommendation]:
    """Nadchodzące eventy, na które user się jeszcze nie zapisał: tagi + podobne osoby, kara za
    odległy termin, max REC_MAX_PER_CATEGORY z jednej kategorii.

    `weights` — opcjonalne nadpisanie REC_WEIGHTS (sandbox); `now` — punkt odniesienia (testy).
    """
    ranked = recommend_breakdown(storage, user, weights=weights, now=now)
    return [
        Recommendation(event=r.event, score=r.score, reason=recommendation_reason(r))
        for r in _diversify(ranked, limit)
    ]


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
