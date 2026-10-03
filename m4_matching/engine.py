"""
M4 — silnik matchingu i rekomendacji. CZYSTA LOGIKA: zero importów streamlit.

SZKIELET: podobieństwo Jaccarda po tagach. Zakres do zrobienia: m4_matching/TASK_SPEC.md
Publiczne API (kontrakt — sygnatur nie zmieniamy bez PR):
    match_for_event(storage, user, event_id, *, limit=10) -> list[MatchResult]
    recommend_events(storage, user, *, limit=5) -> list[Recommendation]
"""

from __future__ import annotations

from datetime import datetime

from shared.models import MatchResult, Recommendation, User
from shared.storage import Storage


def tag_similarity(a: list[str], b: list[str]) -> tuple[float, list[str]]:
    """Jaccard |A∩B| / |A∪B| + lista wspólnych tagów (kolejność jak w `a`)."""
    set_a, set_b = set(a), set(b)
    union = set_a | set_b
    if not union:
        return 0.0, []
    shared = [t for t in a if t in set_b]
    return len(shared) / len(union), shared


def _reason(shared: list[str]) -> str:
    if not shared:
        return "Idziecie na to samo wydarzenie"
    return "Oboje lubicie: " + ", ".join(shared[:3])


def match_for_event(storage: Storage, user: User, event_id: str, *, limit: int = 10) -> list[MatchResult]:
    """Osoby zapisane na event (bez `user`, tylko open_to_meet), od najlepiej dopasowanej."""
    attendee_ids = [
        a.user_id for a in storage.list_attendees(event_id)
        if a.user_id != user.id and a.open_to_meet
    ]
    results: list[MatchResult] = []
    for other in storage.get_users(attendee_ids).values():
        score, shared = tag_similarity(user.tags, other.tags)
        results.append(MatchResult(
            user=other, event_id=event_id, score=round(score, 3),
            shared_tags=shared, reason=_reason(shared),
        ))
    results.sort(key=lambda m: (-m.score, m.user.name))
    return results[:limit]


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
        recs.append(Recommendation(event=event, score=round(score, 3), reason="Pasuje do: " + ", ".join(shared)))
    recs.sort(key=lambda r: (-r.score, r.event.start))
    return recs[:limit]


if __name__ == "__main__":  # python -m m4_matching.engine  — szybki podgląd na mockach
    from shared.mock_data import DEMO_USER_ID

    store = Storage(":memory:")
    me = store.get_user(DEMO_USER_ID)
    assert me is not None
    for m in match_for_event(store, me, "e_jazz_alchemia"):
        print(f"{m.score:.2f}  {m.user.name:<8} {m.reason}")
    print("---")
    for r in recommend_events(store, me):
        print(f"{r.score:.2f}  {r.event.title}  ({r.reason})")
