"""M4-04 — złote przypadki na mockach (scenariusz demo, ARCHITECTURE §11) i wykluczenia.

Złote przypadki opisują ZACHOWANIE, którego oczekujemy od rankingu na personach z
shared/mock_data.py — jeśli zmiana wag je psuje, psuje też demo.
"""

from __future__ import annotations

import pytest

from m4_matching.engine import match_for_event
from shared.models import User
from shared.storage import Storage

JAZZ = "e_jazz_alchemia"
OPERA = "e_opera_carmen"


def _ranking(storage: Storage, user: User, event_id: str, **kwargs) -> list[str]:
    return [m.user.id for m in match_for_event(storage, user, event_id, **kwargs)]


def _persona(storage: Storage, user_id: str) -> User:
    user = storage.get_user(user_id)
    assert user is not None
    return user


# --- złote przypadki: scenariusz demo ------------------------------------ #

def test_demo_step3_bartek_and_natalia_above_tomek(storage: Storage, demo_user: User):
    """Ola na jam session: Bartek i Natalia (wspólne pasje) na górze, Tomek (tylko kino) niżej."""
    ranking = _ranking(storage, demo_user, JAZZ)
    assert set(ranking[:2]) == {"u_bartek", "u_natalia"}
    assert ranking.index("u_tomek") > max(ranking.index("u_bartek"), ranking.index("u_natalia"))


def test_demo_step3_top_match_explains_shared_interests(storage: Storage, demo_user: User):
    top = match_for_event(storage, demo_user, JAZZ)[0]
    assert top.user.id == "u_bartek"
    assert top.shared_tags[:2] == ["jazz", "fotografia"]
    assert top.reason.startswith("Wspólne: jazz, fotografia")


def test_demo_step4_kuba_sees_tomek_first_and_natalia_last(storage: Storage):
    """Kuba (jazz, rock, stand-up…): Tomek dzieli rock i stand-up, z Natalią nic go nie łączy."""
    ranking = _ranking(storage, _persona(storage, "u_kuba"), JAZZ)
    assert ranking[0] == "u_tomek"
    assert ranking[-1] == "u_natalia"
    assert ranking.index("u_ola") < ranking.index("u_bartek")        # jazz + 2 wspólne eventy


def test_natalia_sees_ola_first(storage: Storage):
    """Rzadkie wspólne tagi (sztuka współczesna, fotografia) wygrywają z popularnymi."""
    assert _ranking(storage, _persona(storage, "u_natalia"), JAZZ)[0] == "u_ola"


def test_demo_step5_adding_opera_lifts_ania(storage: Storage, demo_user: User):
    """Ola dopisuje „opera” → na Carmen Ania (opera) zbliża się do Bartka i dostaje to w uzasadnieniu."""
    def ania(user: User):
        return next(m for m in match_for_event(storage, user, OPERA) if m.user.id == "u_ania")

    before = ania(demo_user)
    after = ania(storage.upsert_user(demo_user.model_copy(update={"tags": [*demo_user.tags, "opera"]})))
    assert after.score > before.score
    assert "opera" in after.shared_tags and "opera" in after.reason
    assert "opera" not in before.shared_tags


# --- wykluczenia --------------------------------------------------------- #

@pytest.mark.parametrize("user_id", ["u_ola", "u_kuba", "u_bartek", "u_natalia", "u_tomek"])
def test_attendee_never_sees_self(storage: Storage, user_id: str):
    ranking = _ranking(storage, _persona(storage, user_id), JAZZ)
    assert user_id not in ranking and len(ranking) == 4              # pozostali uczestnicy


def test_mock_hidden_attendee_is_invisible_to_everyone(storage: Storage):
    """u_marta jest na e_kijow_qa z open_to_meet=False — nikt jej tam nie widzi."""
    assert not storage.get_attendance("u_marta", "e_kijow_qa").open_to_meet
    for viewer in storage.list_users():
        assert "u_marta" not in _ranking(storage, viewer, "e_kijow_qa", limit=100)


def test_hidden_twin_is_excluded_even_as_perfect_match(storage: Storage, demo_user: User):
    """Osoba o identycznym profilu byłaby nr 1 — ale open_to_meet=False ją ukrywa."""
    storage.upsert_user(User(id="u_twin", name="Bliźniak", tags=list(demo_user.tags)))
    storage.join_event("u_twin", JAZZ)
    assert _ranking(storage, demo_user, JAZZ)[0] == "u_twin"

    storage.join_event("u_twin", JAZZ, open_to_meet=False)
    assert "u_twin" not in _ranking(storage, demo_user, JAZZ)


def test_toggling_open_to_meet_hides_and_restores(storage: Storage, demo_user: User):
    full = _ranking(storage, demo_user, JAZZ)
    storage.join_event("u_bartek", JAZZ, open_to_meet=False)
    assert _ranking(storage, demo_user, JAZZ) == [u for u in full if u != "u_bartek"]
    storage.join_event("u_bartek", JAZZ, open_to_meet=True)
    assert _ranking(storage, demo_user, JAZZ) == full


def test_left_event_disappears(storage: Storage, demo_user: User):
    assert storage.leave_event("u_natalia", JAZZ)
    assert "u_natalia" not in _ranking(storage, demo_user, JAZZ)


def test_viewer_not_attending_still_sees_attendees(storage: Storage, demo_user: User):
    """Panel pokazuje dopasowania dla każdego klikniętego eventu, nie tylko „moich”."""
    event_id = "e_python_meetup"
    assert storage.get_attendance(demo_user.id, event_id) is None
    assert _ranking(storage, demo_user, event_id)


# --- przypadki brzegowe -------------------------------------------------- #

def test_unknown_or_lonely_event_gives_empty_list(storage: Storage, demo_user: User):
    assert match_for_event(storage, demo_user, "e_nie_istnieje") == []
    assert match_for_event(storage, demo_user, "e_cupping_kawa")      # Ola + Ania
    storage.leave_event("u_ania", "e_cupping_kawa")
    assert match_for_event(storage, demo_user, "e_cupping_kawa") == []


@pytest.mark.parametrize("limit", [0, 1, 2, 4, 10])
def test_limit_returns_prefix_of_full_ranking(storage: Storage, demo_user: User, limit: int):
    full = _ranking(storage, demo_user, JAZZ, limit=100)
    assert _ranking(storage, demo_user, JAZZ, limit=limit) == full[:limit]
