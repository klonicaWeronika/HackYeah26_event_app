"""M4-08 — podobieństwo bio (TF-IDF za flagą WEIGHTS["bio"]) + furtka na inne backendy."""

from __future__ import annotations

import pytest

from m4_matching import bio
from m4_matching.bio import TfidfBioEncoder, bio_key, bio_similarities, stem, tokenize_bio
from m4_matching.engine import WEIGHTS, match_breakdown, match_for_event, match_users
from shared.models import User
from shared.storage import Storage

JAZZ = "e_jazz_alchemia"
BIO_ON = {**WEIGHTS, "bio": 0.10}


def _u(uid: str, text: str, tags: list[str] | None = None, name: str | None = None) -> User:
    return User(id=uid, name=name or uid, bio=text, tags=tags or [])


# --- tokenizacja --------------------------------------------------------- #

@pytest.mark.parametrize(("words", "same"), [
    ("jazz jazzu", True), ("fotografka fotografuję fotografia", True), ("Kraków Krakowie", True),
    ("teatr teatru teatrze", True), ("koncert koncerty", True), ("historia history", True),
    ("techno technologia", False),
])
def test_stemming_groups_inflected_forms(words: str, same: bool):
    stems = set(tokenize_bio(words))
    assert (len(stems) == 1) is same, stems


def test_tokenizer_folds_diacritics_and_drops_stopwords():
    assert tokenize_bio("Śmieję się głośno w kinie, i to bardzo!") == ["smiej", "glosn", "kini"]
    assert tokenize_bio("") == [] and tokenize_bio("🎷 !!! a i o") == []


def test_stem_keeps_short_words():
    assert stem("kino") == "kino"                                     # nie zostawiamy 3-literowych rdzeni
    assert stem("architektura") == "archit"


# --- TF-IDF -------------------------------------------------------------- #

def test_similarity_range_symmetry_and_identity():
    users = [_u("a", "Kocham jazz i fotografię"), _u("b", "Fotografka, jazz na winylach"),
             _u("c", "Biegam rano, meetupy wieczorem"), _u("d", "Kocham jazz i fotografię")]
    sims = {u.id: bio_similarities(u, users, users) for u in users}
    assert sims["a"]["d"] == pytest.approx(1.0)
    assert sims["a"]["c"] == 0.0
    assert 0.0 < sims["a"]["b"] < 1.0
    for a in sims:
        for b, value in sims[a].items():
            assert 0.0 <= value <= 1.0 and sims[b][a] == pytest.approx(value)


def test_rare_shared_word_weighs_more_than_common_one():
    """Wspólne „opera” (rzadkie) > wspólne „Kraków” (w każdym bio)."""
    users = [_u("me", "Kraków, opera, góry"), _u("rare", "Kraków i opera"), _u("common", "Kraków i góry"),
             *(_u(f"x{i}", f"Kraków, góry {i}") for i in range(5))]
    sims = bio_similarities(users[0], users, users)
    assert sims["rare"] > sims["common"]


def test_empty_bio_means_no_signal():
    users = [_u("me", "jazz"), _u("empty", ""), _u("other", "jazz")]
    assert set(bio_similarities(users[0], users, users)) == {"me", "other"}
    assert bio_similarities(users[1], users, users) == {}


def test_vectors_cached_per_bio_version():
    """Rerun bez zmian w profilach = trafienie w cache; edycja bio = przeliczenie."""
    users = [_u("me", "jazz i wino"), _u("o", "jazz")]
    bio._tfidf_vectors.cache_clear()
    bio_similarities(users[0], users, users)
    bio_similarities(users[0], users, users)
    assert bio._tfidf_vectors.cache_info().hits == 1
    edited = [users[0], _u("o", "wino")]
    assert bio_key(edited) != bio_key(users)
    assert bio_similarities(edited[0], edited, edited)["o"] > 0
    assert bio._tfidf_vectors.cache_info().misses == 2


# --- flaga i silnik ------------------------------------------------------ #

def test_flag_off_by_default_and_nothing_is_computed(storage: Storage, demo_user: User, monkeypatch):
    assert WEIGHTS["bio"] == 0.0

    class Exploding:
        def vectors(self, bios):
            raise AssertionError("przy wyłączonej fladze bio nie powinno być liczone")

    monkeypatch.setattr(bio, "ENCODER", Exploding())
    assert all("bio" not in b.signals for b in match_breakdown(storage, demo_user, JAZZ))
    match_users(storage, demo_user)


def test_flag_on_adds_signal_and_keeps_demo_order(storage: Storage, demo_user: User):
    breakdown = match_breakdown(storage, demo_user, JAZZ, weights=BIO_ON)
    assert all("bio" in b.signals for b in breakdown)                 # wszystkie persony mają bio
    ranking = [m.user.id for m in match_for_event(storage, demo_user, JAZZ, weights=BIO_ON)]
    assert set(ranking[:2]) == {"u_bartek", "u_natalia"}              # scenariusz demo bez zmian


def test_bio_alone_can_create_a_global_match(empty_storage: Storage):
    store = empty_storage
    me = store.upsert_user(_u("u_me", "Fotografuję nocą stare kamienice", ["jazz"], "Ja"))
    store.upsert_user(_u("u_o", "Fotografka, kamienice to moja pasja", ["opera"], "Ona"))
    assert match_users(store, me) == []                               # flaga wył. → nic wspólnego
    (match,) = match_users(store, me, weights=BIO_ON)
    assert match.user.id == "u_o" and match.reason == "Podobny opis profilu" and match.score > 0


def test_bio_reason_on_event_when_nothing_else_shared(empty_storage: Storage):
    from datetime import datetime, timedelta

    from shared.models import Event

    store = empty_storage
    start = datetime.now() + timedelta(days=1)
    store.upsert_event(Event(id="e_x", title="x", start=start, venue="X", lat=50.06, lon=19.93))
    me = store.upsert_user(_u("u_me", "Fotografuję nocą stare kamienice", ["jazz"], "Ja"))
    store.upsert_user(_u("u_o", "Fotografka, kamienice to moja pasja", ["opera"], "Ona"))
    store.join_event("u_o", "e_x")
    (match,) = match_for_event(store, me, "e_x", weights=BIO_ON)
    assert match.reason == "Podobny opis profilu"


# --- furtka: inny backend ------------------------------------------------ #

def test_backend_can_be_swapped(storage: Storage, demo_user: User, monkeypatch):
    """Np. embeddingi: dowolny obiekt z vectors()/similarity() — silnik się nie zmienia."""
    class Constant:
        def vectors(self, bios):
            return {uid: (1.0,) for uid, text in bios if text}

        def similarity(self, a, b):
            return 0.5

    monkeypatch.setattr(bio, "ENCODER", Constant())
    breakdown = match_breakdown(storage, demo_user, JAZZ, weights=BIO_ON)
    assert breakdown and all(b.signals["bio"] == 0.5 for b in breakdown)


def test_default_backend_is_tfidf():
    assert isinstance(bio.ENCODER, TfidfBioEncoder)
