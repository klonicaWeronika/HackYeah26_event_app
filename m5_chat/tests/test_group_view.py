"""M5 — UI grup na wydarzenia (AppTest, baza w RAM): czat grupy, zaproszenia, głosowania, wejścia."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from m5_chat.groups import GroupRole, InviteStatus, accept_invite, invite, member_group, role_in, vote
from m5_chat.inbox import _news, _watch_state
from shared.models import event_room_id, group_room_id
from shared.state import View
from shared.storage import Storage

ROOM = group_room_id("g_jazz")   # mocki: Kuba, Bartek, Natalia; Ola ma zaproszenie od Kuby
JAZZ_ALL = event_room_id("e_jazz_alchemia")   # czat wszystkich: Tomek, Natalia, Kuba (msg_seed_event_*)
APP_PATH = str(Path(__file__).resolve().parents[2] / "app.py")


def _group_chat_app():
    from m5_chat.chat_view import render_chat_room
    from shared import state
    from shared.state import View
    from shared.storage import get_storage

    storage = get_storage()
    state.init()
    if state.current_view() is View.CHAT:
        render_chat_room(storage, storage.get_user(state.current_user_id()), state.chat_room_id())


@pytest.fixture
def open_chat(storage: Storage, monkeypatch):
    monkeypatch.setattr("shared.storage._default_storage", storage)

    def run_as(user_id: str, room_id: str = ROOM) -> AppTest:
        at = AppTest.from_function(_group_chat_app, default_timeout=30)
        at.query_params["user"] = user_id
        at.session_state["view"] = View.CHAT
        at.session_state["chat_room_id"] = room_id
        return at.run()

    return run_as


def _crew(at: AppTest) -> str:
    return next(h.value for h in at.get("html") if 'class="m5-crew"' in h.value)


def _texts(at: AppTest) -> str:
    return "\n".join(h.value for h in at.get("html"))


def test_invited_person_sees_crew_but_not_messages_until_joining(open_chat, storage: Storage):
    at = open_chat("u_ola")
    assert "### 🎵 Jam session jazzowy w piwnicy" in [m.value for m in at.markdown]   # nazwa nad czatem
    assert not at.chat_input
    assert "Ktoś idzie od początku?" not in _texts(at)                  # treść dopiero po dołączeniu
    assert "Wiadomości grupy zobaczysz po dołączeniu · 3 wiadomości" in _texts(at)
    assert f"m5_buf_{ROOM}" not in at.session_state                     # nic nie trafia nawet do bufora
    crew = _crew(at)
    assert crew.count("m5-crew-item") == 4 and "zaproszenie" in crew
    assert any("3 osoby w grupie" in c.value for c in at.caption)

    at.button(key="m5_grp_accept_g_jazz").click().run()
    assert not at.exception, at.exception
    assert role_in(storage.get_group("g_jazz"), "u_ola") is GroupRole.MEMBER
    assert at.chat_input and "m5_grp_accept_g_jazz" not in {b.key for b in at.button}
    assert "Ktoś idzie od początku?" in _texts(at)
    crew = _crew(at)
    assert "zaproszenie" not in crew and "m5-crew-new" in crew                          # nowy awatar wjeżdża
    assert any("4 osoby w grupie" in c.value for c in at.caption)


def test_declining_goes_back_to_map(open_chat, storage: Storage):
    at = open_chat("u_ola")
    at.button(key="m5_grp_decline_g_jazz").click().run()
    assert at.session_state["view"] == View.MAP
    assert storage.get_group("g_jazz").invite_for("u_ola") is None


def test_outsider_sees_lock_not_messages(open_chat):
    at = open_chat("u_marta")
    assert any("Nie należysz do tej grupy" in w.value for w in at.warning)
    assert not any("Ktoś idzie od początku?" in h.value for h in at.get("html"))
    assert not at.chat_input


def test_invite_from_chat_dropdown_starts_vote_on_chat(open_chat, storage: Storage):
    at = open_chat("u_kuba")
    assert at.button(key="m5_pick_m5_grp_add_g_jazz_u_tomek")     # „Idą” bez członków i zaproszonych
    keys = {b.key for b in at.button}
    assert "m5_pick_m5_grp_add_g_jazz_u_bartek" not in keys and "m5_pick_m5_grp_add_g_jazz_u_ola" not in keys
    at.button(key="m5_pick_m5_grp_add_g_jazz_u_tomek").click().run()
    assert not at.exception, at.exception
    invitation = storage.get_group("g_jazz").invite_for("u_tomek")
    assert invitation is not None and not invitation.is_sent
    cards = [h.value for h in at.get("html") if "Kuba chce zaprosić do grupy: Tomek" in h.value]
    assert cards and "Za: 1/3" in cards[0]
    assert "głosowanie" in _crew(at)
    assert not [b for b in at.button if (b.key or "").startswith("m5_vote_yes_")]   # zapraszający już jest za


def test_every_member_votes_on_chat_until_invite_is_sent(open_chat, storage: Storage):
    assert invite(storage, "e_jazz_alchemia", "u_kuba", "u_tomek").status is InviteStatus.VOTING
    card = storage.list_messages(ROOM)[-1]
    for voter in ("u_bartek", "u_natalia"):
        at = open_chat(voter)
        at.button(key=f"m5_vote_yes_{card.id}").click().run()
        assert not at.exception, at.exception
    assert storage.get_group("g_jazz").invite_for("u_tomek").is_sent
    at = open_chat("u_kuba")
    assert any("Zaproszenie wysłane" in h.value for h in at.get("html"))
    assert any("Wszyscy za ✅ — zaproszenie wysłane: Tomek" in h.value for h in at.get("html"))


def test_vote_against_rejects(open_chat, storage: Storage):
    invite(storage, "e_jazz_alchemia", "u_kuba", "u_tomek")
    card = storage.list_messages(ROOM)[-1]
    at = open_chat("u_natalia")
    at.button(key=f"m5_vote_no_{card.id}").click().run()
    assert storage.get_group("g_jazz").invite_for("u_tomek") is None
    assert any("Zakończone" in h.value for h in at.get("html"))


def test_switch_replaces_group_chat_with_everyone_and_back(open_chat):
    at = open_chat("u_kuba")
    switch = at.segmented_control(key="m5_switch_e_jazz_alchemia")
    assert switch.value == ROOM and switch.formatted_values == ["Grupa · 3"]
    switch.set_value(JAZZ_ALL).run()                                        # „Wszyscy” w tym samym miejscu
    assert at.session_state["chat_room_id"] == JAZZ_ALL
    assert "W zeszłym tygodniu było luźno" in _texts(at) and "Ktoś idzie od początku?" not in _texts(at)
    assert any("czat wszystkich uczestników" in c.value for c in at.caption)
    assert at.chat_input
    at.segmented_control(key="m5_switch_e_jazz_alchemia").set_value(ROOM).run()
    assert at.session_state["chat_room_id"] == ROOM and "Ktoś idzie od początku?" in _texts(at)


def test_everyone_chat_without_group_offers_invite_instead_of_switch(open_chat, storage: Storage):
    at = open_chat("u_marta", room_id=JAZZ_ALL)                 # niezapisana — czat jest dla wszystkich
    assert not at.get("button_group") and at.button(key="m5_pick_m5_chat_invite_e_jazz_alchemia_u_tomek")
    at.chat_input(key=f"m5_input_{JAZZ_ALL}").set_value("Hej, czy jest jeszcze miejsce?").run()
    assert storage.list_messages(JAZZ_ALL)[-1].text == "Hej, czy jest jeszcze miejsce?"


def test_leave_group_button(open_chat, storage: Storage):
    at = open_chat("u_kuba")
    at.button(key="m5_grp_leave_btn_g_jazz").click().run()
    assert at.session_state["view"] == View.MAP
    assert storage.get_group("g_jazz").members == ["u_bartek", "u_natalia"]


# --------------------------------------------------------------------------- #
# Wejścia w całej aplikacji: panel wydarzenia (M1), karta pasującej osoby (M3), skrzynka „Ekipy”
# --------------------------------------------------------------------------- #

@pytest.fixture
def app_storage(tmp_path, monkeypatch) -> Storage:
    store = Storage(tmp_path / "groups.db")
    monkeypatch.setattr("shared.storage._default_storage", store)
    yield store
    store.close()


def _run_app(user_id: str = "u_ola", event_id: str | None = None) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.query_params["user"] = user_id
    at.session_state["selected_event_id"] = event_id
    return at.run()


def test_panel_dropdown_invites_and_opens_group_chat(app_storage):
    at = _run_app(event_id="e_rejs_kino")
    assert {"m5_pick_m5_grp_new_e_rejs_kino_u_kuba", "m5_pick_m5_grp_new_e_rejs_kino_u_tomek"} <= {
        b.key for b in at.button
    }
    at.button(key="m5_pick_m5_grp_new_e_rejs_kino_u_kuba").click().run()
    assert not at.exception, at.exception
    group = member_group(app_storage, "e_rejs_kino", "u_ola")
    assert at.session_state["view"] == View.CHAT
    assert at.session_state["chat_room_id"] == group_room_id(group.id)
    assert role_in(group, "u_kuba") is GroupRole.INVITED
    assert any("Zaproszenie wysłane" in t.value for t in at.toast)
    assert at.button(key="m5_grp_open_e_rejs_kino")                     # panel: „Czat grupy · 1 osoba”


def test_panel_has_group_chat_next_to_everyone_chat(app_storage):
    at = _run_app(event_id="e_jazz_alchemia")                           # Ola: zaproszenie, bez grupy
    entry = at.button(key="m5_evt_open_e_jazz_alchemia")
    assert entry.label == "Czat wydarzenia" and "wiadomości: 3" in entry.help
    assert at.button(key="m5_grp_view_g_jazz")
    entry.click().run()
    assert not at.exception, at.exception
    assert at.session_state["view"] == View.CHAT and at.session_state["chat_room_id"] == JAZZ_ALL
    assert at.segmented_control(key="m5_switch_e_jazz_alchemia").value == JAZZ_ALL   # „Grupa” = zaproszenie


def test_match_card_writes_in_event_context_not_dm(app_storage):
    at = _run_app(event_id="e_rejs_kino")
    keys = {b.key for b in at.button}
    assert "m1_match_e_rejs_kino_u_tomek_group" in keys and "m1_match_e_rejs_kino_u_tomek_dm" not in keys
    at.button(key="m1_match_e_rejs_kino_u_tomek_group").click().run()
    group = member_group(app_storage, "e_rejs_kino", "u_ola")
    assert at.session_state["chat_room_id"] == group_room_id(group.id)
    assert group.invite_for("u_tomek").is_sent


def test_match_card_of_inviter_opens_their_invitation(app_storage):
    at = _run_app(event_id="e_jazz_alchemia")
    at.button(key="m1_match_e_jazz_alchemia_u_kuba_group").click().run()
    assert at.session_state["chat_room_id"] == ROOM                      # zaproszenie Kuby, bez nowej grupy
    assert member_group(app_storage, "e_jazz_alchemia", "u_ola") is None
    assert at.button(key="m5_grp_accept_g_jazz")


def test_inbox_lists_invitation_and_opens_it(app_storage):
    at = _run_app()
    entry = at.button(key="m5_inbox_inv_g_jazz")
    assert "Kuba" in entry.label and "Jam session" in entry.label
    entry.click().run()
    assert at.session_state["view"] == View.CHAT and at.session_state["chat_room_id"] == ROOM
    assert at.session_state["selected_event_id"] == "e_jazz_alchemia"              # panel: wydarzenie grupy


def test_notifier_announces_news_except_for_open_chat(storage: Storage):
    title = "🎵 Jam session jazzowy w piwnicy"
    natalia = _watch_state(storage, "u_natalia")
    result = invite(storage, "e_jazz_alchemia", "u_bartek", "u_tomek")
    new = set(_watch_state(storage, "u_natalia") - natalia)
    assert [text for text, _ in _news(storage, new, None)] == [
        f"Głosowanie w grupie {title}: zaproszenie dla Tomek",
    ]
    assert _news(storage, new, "g_jazz") == []          # otwarty czat grupy sam pokazuje kartę głosowania

    tomek = _watch_state(storage, "u_tomek")                    # głosowanie trwa — Tomek jeszcze nic nie wie
    for voter in ("u_kuba", "u_natalia"):
        vote(storage, "g_jazz", result.invite.id, voter, True)
    new = set(_watch_state(storage, "u_tomek") - tomek)
    assert [text for text, _ in _news(storage, new, None)] == [f"Bartek zaprasza Cię do ekipy: {title}"]

    kuba = _watch_state(storage, "u_kuba")
    accept_invite(storage, "g_jazz", "u_ola")
    new = set(_watch_state(storage, "u_kuba") - kuba)
    assert [text for text, _ in _news(storage, new, None)] == [f"Ola dołącza do Twojej grupy: {title}"]
