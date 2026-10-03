"""M4 — testy silnika matchingu i rekomendacji (czysta logika, baza w RAM)."""

from m4_matching.engine import match_for_event, recommend_events, tag_similarity
from shared.models import User
from shared.storage import Storage


def test_tag_similarity_bounds():
    assert tag_similarity([], []) == (0.0, [])
    assert tag_similarity(["a", "b"], ["a", "b"])[0] == 1.0
    score, shared = tag_similarity(["a", "b"], ["b", "c"])
    assert 0 < score < 1 and shared == ["b"]


def test_matches_exclude_self_and_hidden_users(storage: Storage, demo_user: User):
    matches = match_for_event(storage, demo_user, "e_jazz_alchemia")
    ids = [m.user.id for m in matches]
    assert demo_user.id not in ids and ids
    assert all(0 <= m.score <= 1 and m.event_id == "e_jazz_alchemia" for m in matches)
    assert [m.score for m in matches] == sorted((m.score for m in matches), reverse=True)

    hidden = match_for_event(storage, demo_user, "e_kijow_qa")   # u_marta ma open_to_meet=False
    assert "u_marta" not in [m.user.id for m in hidden]


def test_best_match_shares_interests(storage: Storage, demo_user: User):
    best = match_for_event(storage, demo_user, "e_jazz_alchemia")[0]
    assert best.shared_tags and best.reason


def test_recommendations_skip_joined_events(storage: Storage, demo_user: User):
    joined = {a.event_id for a in storage.list_user_attendance(demo_user.id)}
    recs = recommend_events(storage, demo_user, limit=10)
    assert recs and not joined.intersection(r.event.id for r in recs)
