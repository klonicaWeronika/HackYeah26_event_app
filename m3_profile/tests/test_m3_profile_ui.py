"""M3 — testy UI profilu przez AppTest (izolowana baza w tmp_path, nigdy data/app.db)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from m5_chat import chat_view
from shared.config import FEATURES
from shared.mock_data import DEMO_USER_ID
from shared.models import AttendanceStatus
from shared.state import Keys, View
from shared.storage import Storage


def _editor_app() -> None:
    from m3_profile.views import render_profile_editor
    from shared import state
    from shared.storage import get_storage

    storage = get_storage()
    state.init()
    render_profile_editor(storage, storage.get_user(state.current_user_id()))


@pytest.fixture
def ui_storage(tmp_path, monkeypatch) -> Storage:
    store = Storage(tmp_path / "m3_ui.db")
    monkeypatch.setattr("shared.storage._default_storage", store)
    yield store
    store.close()


@pytest.fixture
def editor(ui_storage) -> AppTest:
    at = AppTest.from_function(_editor_app, default_timeout=15)
    at.query_params["user"] = DEMO_USER_ID
    at.session_state[Keys.VIEW] = View.PROFILE_EDIT
    at.run()
    assert not at.exception, at.exception
    return at


def _jpeg(size=(600, 900), color=(30, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def _run(at: AppTest) -> AppTest:
    at.run()
    assert not at.exception, at.exception
    return at


def _upload(at: AppTest, data: bytes, name: str = "zdjecie.jpg") -> AppTest:
    at.file_uploader[0].set_value((name, data, "image/jpeg"))
    return _run(at)


def _button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def _preview_html(at: AppTest) -> str:
    return next(m.value for m in at.markdown if "border-radius:50%" in m.value)


# --------------------------------------------------------------------------- #

def test_uploader_is_outside_the_form(editor):
    """W st.form plik ginie przy rerunie — uploader musi być poza formularzem."""
    assert editor.file_uploader[0].form_id == ""
    assert {"jpg", "jpeg", "png", "webp"} <= {t.lstrip(".") for t in editor.file_uploader[0].allowed_type}


def test_upload_shows_preview_but_saves_only_on_submit(editor, ui_storage):
    before = ui_storage.get_user(DEMO_USER_ID).avatar_url
    _upload(editor, _jpeg())
    assert "url('data:image/jpeg;base64," in _preview_html(editor)
    assert any("Podgląd" in c.value for c in editor.caption)
    assert not editor.error
    assert ui_storage.get_user(DEMO_USER_ID).avatar_url == before     # jeszcze nie zapisane

    _button(editor, "Zapisz").click()
    _run(editor)
    saved = ui_storage.get_user(DEMO_USER_ID).avatar_url
    assert saved.startswith("data:image/jpeg;base64,") and len(saved) < 60_000
    assert editor.session_state[Keys.VIEW] is View.MAP
    assert "m3_avatar_draft" not in editor.session_state


@pytest.mark.parametrize("data, fragment", [
    pytest.param(b"to nie jest obraz", "uszkodzony", id="uszkodzony-plik"),
    pytest.param(b"\xff" * (5 * 1024 * 1024 + 1), "5 MB", id="za-duzy-5MB"),
])
def test_bad_file_shows_polish_error_without_exception(editor, ui_storage, data, fragment):
    before = ui_storage.get_user(DEMO_USER_ID).avatar_url
    _upload(editor, data)
    assert editor.error and fragment in editor.error[0].value
    assert "m3_avatar_draft" not in editor.session_state
    _button(editor, "Zapisz").click()
    _run(editor)
    assert ui_storage.get_user(DEMO_USER_ID).avatar_url == before


def test_remove_photo_then_save_falls_back_to_initials(editor, ui_storage):
    _button(editor, "🗑️ Usuń zdjęcie").click()
    _run(editor)
    assert "url(" not in _preview_html(editor)                       # podgląd: same inicjały
    _button(editor, "Zapisz").click()
    _run(editor)
    assert ui_storage.get_user(DEMO_USER_ID).avatar_url is None


def test_clearing_uploader_discards_draft(editor):
    _upload(editor, _jpeg())
    assert "m3_avatar_draft" in editor.session_state
    editor.file_uploader[0].clear()
    _run(editor)
    assert "m3_avatar_draft" not in editor.session_state


def test_back_to_map_discards_unsaved_photo(editor, ui_storage):
    before = ui_storage.get_user(DEMO_USER_ID).avatar_url
    _upload(editor, _jpeg())
    editor.button(key="m3_back_from_editor").click()
    _run(editor)
    assert editor.session_state[Keys.VIEW] is View.MAP
    assert "m3_avatar_draft" not in editor.session_state
    assert ui_storage.get_user(DEMO_USER_ID).avatar_url == before


# --------------------------------------------------------------------------- #
# M3-03: walidacja przy polach, zapis w on_click
# --------------------------------------------------------------------------- #

def _field(at: AppTest, kind: str, field: str):
    return getattr(at, kind)(key=f"m3_pe_{field}_{DEMO_USER_ID}")


def _save(at: AppTest) -> AppTest:
    _button(at, "Zapisz").click()
    return _run(at)


def test_editor_widgets_use_per_user_keys(editor, ui_storage):
    ola = ui_storage.get_user(DEMO_USER_ID)
    assert _field(editor, "text_input", "name").value == ola.name
    assert _field(editor, "text_area", "bio").value == ola.bio
    assert _field(editor, "multiselect", "tags").value == ola.tags


def test_invalid_profile_is_not_saved_and_errors_show_under_fields(editor, ui_storage):
    before = ui_storage.get_user(DEMO_USER_ID)
    _field(editor, "text_input", "name").input("   ")
    _field(editor, "multiselect", "tags").set_value(["jazz", "kino"])
    _save(editor)
    messages = [e.value for e in editor.error]
    assert any("imię" in m.lower() for m in messages)
    assert any("co najmniej 3" in m for m in messages)
    assert ui_storage.get_user(DEMO_USER_ID) == before                 # nic nie zapisane
    assert editor.session_state[Keys.VIEW] is View.PROFILE_EDIT       # zostajemy w edytorze
    assert editor.button(key="m3_back_from_editor")                   # „Wróć” nadal dostępne


def test_valid_edit_is_normalized_saved_with_toast_and_returns_to_map(editor, ui_storage):
    _field(editor, "text_input", "name").input("  Ola   K. ")
    _field(editor, "text_area", "bio").input("  Nowa w Krakowie.  ")
    _field(editor, "multiselect", "tags").set_value(["jazz", "kino", "#Opera", "OPERA"])
    _save(editor)
    saved = ui_storage.get_user(DEMO_USER_ID)
    assert (saved.name, saved.bio, saved.tags) == ("Ola K.", "Nowa w Krakowie.", ["jazz", "kino", "opera"])
    assert any("Profil zapisany" in t.value for t in editor.toast)
    assert editor.session_state[Keys.VIEW] is View.MAP
    assert not editor.error


def test_fixing_errors_then_saving_clears_messages(editor, ui_storage):
    _field(editor, "multiselect", "tags").set_value(["jazz"])
    _save(editor)
    assert editor.error
    _field(editor, "multiselect", "tags").set_value(["jazz", "kino", "teatr"])
    _save(editor)
    assert not editor.error and "m3_pe_errors" not in editor.session_state
    assert ui_storage.get_user(DEMO_USER_ID).tags == ["jazz", "kino", "teatr"]


def test_back_to_map_clears_validation_errors(editor):
    _field(editor, "multiselect", "tags").set_value([])
    _save(editor)
    assert "m3_pe_errors" in editor.session_state
    editor.button(key="m3_back_from_editor").click()
    _run(editor)
    assert "m3_pe_errors" not in editor.session_state


def test_tag_edit_changes_matching_immediately(editor, ui_storage):
    """DoD: edycja tagów od razu wpływa na dopasowania M4 (bez restartu) — zapis unieważnia cache."""
    from m4_matching.engine import match_for_event

    event_id = "e_jazz_alchemia"
    def scores() -> dict[str, float]:
        me = ui_storage.get_user(DEMO_USER_ID)
        return {m.user.id: m.score for m in match_for_event(ui_storage, me, event_id)}

    before = scores()
    _field(editor, "multiselect", "tags").set_value(["bieganie", "rower", "joga"])
    _save(editor)
    after = scores()
    assert before != after


def test_editor_renders_inside_full_app(ui_storage):
    """Integracja z app.py (M1): edytor w środkowej kolumnie, bez kolizji kluczy z headerem/panelem."""
    from pathlib import Path

    at = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "app.py"), default_timeout=30)
    at.query_params["user"] = DEMO_USER_ID
    at.session_state[Keys.VIEW] = View.PROFILE_EDIT
    _run(at)
    assert at.text_input(key=f"m3_pe_name_{DEMO_USER_ID}").value == ui_storage.get_user(DEMO_USER_ID).name
    _button(at, "Zapisz").click()
    _run(at)
    assert at.session_state[Keys.VIEW] is View.MAP


# --------------------------------------------------------------------------- #
# M3-04: onboarding
# --------------------------------------------------------------------------- #

APP_PATH = str(Path(__file__).resolve().parents[2] / "app.py")
NEW = "new"


def _app(query_params: dict | None = None, **session) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.query_params.update(query_params or {"user": DEMO_USER_ID})
    for key, value in session.items():
        at.session_state[key] = value
    return _run(at)


def _start_onboarding(at: AppTest) -> AppTest:
    at.button(key="m3_user_switch_new").click()                       # „➕ Nowy profil” w ⚙️ Opcje (M1)
    _run(at)
    assert at.session_state["m3_onboarding"] is True
    assert any("Załóż profil" in s.value for s in at.subheader)
    return at


def _fill_onboarding(at: AppTest, name: str, tags: list[str], bio: str = "") -> AppTest:
    at.text_input(key=f"m3_pe_name_{NEW}").input(name)
    at.text_area(key=f"m3_pe_bio_{NEW}").input(bio)
    at.multiselect(key=f"m3_pe_tags_{NEW}").set_value(tags)
    _button(at, "Utwórz profil").click()
    return _run(at)


def _header_html(at: AppTest) -> str:
    return next(m.value for m in at.markdown if 'class="m1-header"' in m.value)


def test_onboarding_creates_profile_logs_in_and_survives_refresh(ui_storage):
    users_before = {u.id for u in ui_storage.list_users()}
    at = _start_onboarding(_app())
    _fill_onboarding(at, "  Ewa  ", ["jazz", "kino", "#Planszówki"], bio="Nowa w Krakowie")

    new_ids = {u.id for u in ui_storage.list_users()} - users_before
    assert len(new_ids) == 1
    new_id = new_ids.pop()
    ewa = ui_storage.get_user(new_id)
    assert new_id.startswith("u_") and (ewa.name, ewa.tags) == ("Ewa", ["jazz", "kino", "planszówki"])
    # zalogowana: sesja + URL + header + przełącznik (zsynchronizowany przed utworzeniem widgetu)
    assert at.session_state[Keys.USER_ID] == new_id and at.query_params["user"] == new_id
    assert at.session_state[Keys.VIEW] is View.MAP and "m3_onboarding" not in at.session_state
    assert "Ewa" in _header_html(at) and at.selectbox(key="m3_user_switch").value == new_id
    assert any("Witaj, Ewa" in t.value for t in at.toast)

    refreshed = _app(dict(at.query_params))                            # F5 = nowa sesja z tym samym URL
    assert refreshed.session_state[Keys.USER_ID] == new_id and "Ewa" in _header_html(refreshed)


def test_onboarding_validates_like_editor_and_creates_nothing(ui_storage):
    count = len(ui_storage.list_users())
    at = _fill_onboarding(_start_onboarding(_app()), "   ", ["jazz"])
    messages = [e.value for e in at.error]
    assert any("imię" in m.lower() for m in messages) and any("co najmniej 3" in m for m in messages)
    assert len(ui_storage.list_users()) == count
    assert at.session_state["m3_onboarding"] is True and at.session_state[Keys.USER_ID] == DEMO_USER_ID


def test_onboarding_with_photo(ui_storage):
    at = _start_onboarding(_app())
    _upload(at, _jpeg())
    _fill_onboarding(at, "Foto", ["jazz", "kino", "kawa"])
    created = ui_storage.get_user(at.session_state[Keys.USER_ID])
    assert created.avatar_url.startswith("data:image/jpeg;base64,")


def test_back_from_onboarding_creates_nothing(ui_storage):
    count = len(ui_storage.list_users())
    at = _start_onboarding(_app())
    at.button(key="m3_back_from_onboarding").click()
    _run(at)
    assert at.session_state[Keys.VIEW] is View.MAP and "m3_onboarding" not in at.session_state
    assert len(ui_storage.list_users()) == count


def test_leaving_onboarding_sideways_then_edit_shows_normal_editor(ui_storage):
    """Np. „💬 Czat wydarzenia” w trakcie onboardingu -> późniejsze „Edytuj profil” to zwykła edycja."""
    at = _start_onboarding(_app())
    at.session_state[Keys.VIEW] = View.CHAT
    at.session_state[Keys.CHAT_ROOM_ID] = "event:e_jazz_alchemia"
    _run(at)
    assert "m3_onboarding" not in at.session_state
    at.session_state[Keys.VIEW] = View.PROFILE_EDIT
    _run(at)
    assert any("Twój profil" in s.value for s in at.subheader)


def test_new_person_sees_matches_after_joining_event(ui_storage):
    """DoD M3-04: nowa osoba -> „Idę!” (M5) -> widzi pasujące osoby i sama pojawia się u innych."""
    from m4_matching.engine import match_for_event

    event_id = "e_jazz_alchemia"
    at = _start_onboarding(_app(**{Keys.SELECTED_EVENT_ID: event_id}))
    _fill_onboarding(at, "Ewa", ["jazz", "fotografia", "wino"])
    new_id = at.session_state[Keys.USER_ID]
    assert at.session_state[Keys.SELECTED_EVENT_ID] == event_id        # panel wydarzenia został otwarty
    at.segmented_control(key=f"m5_status_{new_id}_{event_id}").set_value(AttendanceStatus.GOING)  # „🙋 Idę!” (M5)
    _run(at)
    match_keys = [b.key for b in at.button if (b.key or "").startswith(f"m1_match_{event_id}_")]
    assert match_keys, "nowa osoba powinna widzieć karty pasujących osób"
    ola = ui_storage.get_user(DEMO_USER_ID)
    assert new_id in {m.user.id for m in match_for_event(ui_storage, ola, event_id)}


def test_unknown_user_in_url_falls_back_to_demo_user(ui_storage):
    at = _app({"user": "u_nie_ma_takiego"})
    assert at.session_state[Keys.USER_ID] == DEMO_USER_ID and at.query_params["user"] == DEMO_USER_ID
    assert at.selectbox(key="m3_user_switch").value == DEMO_USER_ID
    assert any("Nie znaleziono profilu" in t.value for t in at.toast)


def _onboarding_only_app() -> None:
    import streamlit as st

    from m3_profile.views import render_onboarding
    from shared import state
    from shared.storage import get_storage

    state.init()
    created = render_onboarding(get_storage())
    if created is not None:
        st.write(f"utworzono:{created.id}")


def test_render_onboarding_returns_created_user_once(ui_storage):
    at = AppTest.from_function(_onboarding_only_app, default_timeout=15)
    _run(at)
    _fill_onboarding(at, "Ewa", ["jazz", "kino", "kawa"])
    new_id = at.session_state[Keys.USER_ID]
    assert any(m.value == f"utworzono:{new_id}" for m in at.markdown)
    _run(at)                                                           # kolejny przebieg: znów formularz
    assert not any(m.value.startswith("utworzono:") for m in at.markdown)


# --------------------------------------------------------------------------- #
# M3-05: karta osoby — klucze, „Profil”, „Napisz” (API M5)
# --------------------------------------------------------------------------- #

def _cards_app() -> None:
    from m3_profile.views import render_user_card
    from shared import state
    from shared.storage import get_storage

    storage = get_storage()
    state.init()
    kuba, ola = storage.get_user("u_kuba"), storage.get_user("u_ola")
    render_user_card(kuba, key="t_a")
    render_user_card(kuba, key="t_b")          # ta sama osoba drugi raz (np. dwie listy) -> inne klucze
    render_user_card(ola, key="t_me")          # własna karta


@pytest.fixture
def cards(ui_storage) -> AppTest:
    at = AppTest.from_function(_cards_app, default_timeout=15)
    at.query_params["user"] = DEMO_USER_ID
    return at


def test_card_keys_are_unique_and_profile_button_opens_profile(cards):
    _run(cards)
    assert {b.key for b in cards.button} >= {"t_a_profile", "t_b_profile", "t_me_profile"}
    cards.button(key="t_b_profile").click()
    _run(cards)
    assert cards.session_state[Keys.VIEW] is View.PROFILE_VIEW
    assert cards.session_state[Keys.VIEWED_USER_ID] == "u_kuba"


def test_dm_button_hidden_when_feature_flag_off(cards, monkeypatch):
    monkeypatch.setitem(FEATURES, "dm_chat", False)
    monkeypatch.setattr(chat_view, "open_dm", lambda me, other: None, raising=False)
    _run(cards)
    assert not [b for b in cards.button if b.key.endswith("_dm")]


def test_dm_button_hidden_until_m5_delivers_open_dm(cards, monkeypatch):
    monkeypatch.setitem(FEATURES, "dm_chat", True)
    monkeypatch.delattr(chat_view, "open_dm", raising=False)
    _run(cards)                                                         # nic się nie wywraca
    assert not [b for b in cards.button if b.key.endswith("_dm")]


def test_dm_button_calls_m5_open_dm_with_me_and_other(cards, monkeypatch):
    calls = []
    monkeypatch.setitem(FEATURES, "dm_chat", True)
    monkeypatch.setattr(chat_view, "open_dm", lambda me, other: calls.append((me, other)), raising=False)
    _run(cards)
    dm_keys = {b.key for b in cards.button if b.key.endswith("_dm")}
    assert dm_keys == {"t_a_dm", "t_b_dm"}                              # bez własnej karty
    cards.button(key="t_a_dm").click()
    _run(cards)
    assert calls == [(DEMO_USER_ID, "u_kuba")]


def test_match_cards_in_full_app_panel(ui_storage):
    """Prawy panel M1: karta każdej pasującej osoby ma badge + pasek wyniku i przyciski z kluczami M1."""
    from m4_matching.engine import match_for_event

    event_id = "e_jazz_alchemia"
    at = _app(**{Keys.SELECTED_EVENT_ID: event_id})
    matches = match_for_event(ui_storage, ui_storage.get_user(DEMO_USER_ID), event_id)
    bars = [m.value for m in at.markdown if 'aria-label="Dopasowanie' in m.value]
    assert matches and len(bars) == len(matches)
    for m in matches:
        assert at.button(key=f"m1_match_{event_id}_{m.user.id}_profile")


# --------------------------------------------------------------------------- #
# M3-06: podgląd profilu
# --------------------------------------------------------------------------- #

def _markdown_text(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def test_card_to_profile_and_back_keeps_selected_event(ui_storage):
    """DoD M3-06: karta w panelu -> profil -> powrót do mapy z zachowanym wybranym wydarzeniem."""
    event_id = "e_jazz_alchemia"
    at = _app(**{Keys.SELECTED_EVENT_ID: event_id})
    at.button(key=f"m1_match_{event_id}_u_bartek_profile").click()
    _run(at)
    assert at.session_state[Keys.VIEW] is View.PROFILE_VIEW
    assert at.session_state[Keys.VIEWED_USER_ID] == "u_bartek"
    text = _markdown_text(at)
    assert "Bartek" in text and "Wspólne zainteresowania" in text and "Wspólne wydarzenia" in text
    assert "✓ jazz" in text and "Jam session jazzowy" in text
    assert at.button(key=f"m3_pv_show_{event_id}")                     # wspólne wydarzenie z przyciskiem
    at.button(key="m3_back_from_profile").click()
    _run(at)
    assert at.session_state[Keys.VIEW] is View.MAP
    assert at.session_state[Keys.SELECTED_EVENT_ID] == event_id


def test_profile_lists_only_upcoming_events(ui_storage):
    from datetime import timedelta

    from shared.models import Event, now

    past = Event(id="e_minione", title="Minione wydarzenie", start=now() - timedelta(days=3),
                 venue="X", lat=50.06, lon=19.94)
    ui_storage.upsert_event(past)
    ui_storage.join_event("u_bartek", past.id)
    at = _app(**{Keys.VIEW: View.PROFILE_VIEW, Keys.VIEWED_USER_ID: "u_bartek"})
    assert "Minione wydarzenie" not in _markdown_text(at)
    assert not [b for b in at.button if b.key == "m3_pv_show_e_minione"]


def test_show_event_button_opens_it_on_map(ui_storage):
    at = _app(**{Keys.VIEW: View.PROFILE_VIEW, Keys.VIEWED_USER_ID: "u_bartek"})
    at.button(key="m3_pv_show_e_fotospacer").click()
    _run(at)
    assert at.session_state[Keys.VIEW] is View.MAP
    assert at.session_state[Keys.SELECTED_EVENT_ID] == "e_fotospacer"


def test_own_profile_offers_edit_not_dm(ui_storage, monkeypatch):
    monkeypatch.setitem(FEATURES, "dm_chat", True)
    monkeypatch.setattr(chat_view, "open_dm", lambda me, other: None, raising=False)
    at = _app(**{Keys.VIEW: View.PROFILE_VIEW, Keys.VIEWED_USER_ID: DEMO_USER_ID})
    assert "To Twój profil" in _markdown_text(at)
    assert not [b for b in at.button if b.key == "m3_pv_dm"]
    at.button(key="m3_pv_edit").click()
    _run(at)
    assert at.session_state[Keys.VIEW] is View.PROFILE_EDIT


def test_dm_button_on_profile_calls_m5(ui_storage, monkeypatch):
    calls = []
    monkeypatch.setitem(FEATURES, "dm_chat", True)
    monkeypatch.setattr(chat_view, "open_dm", lambda me, other: calls.append((me, other)), raising=False)
    at = _app(**{Keys.VIEW: View.PROFILE_VIEW, Keys.VIEWED_USER_ID: "u_bartek"})
    at.button(key="m3_pv_dm").click()
    _run(at)
    assert calls == [(DEMO_USER_ID, "u_bartek")]


# --------------------------------------------------------------------------- #
# M3-09: persony demo w przełączniku
# --------------------------------------------------------------------------- #

def test_switcher_shows_personas_in_demo_order_and_still_switches(ui_storage):
    from m3_profile.personas import DEMO_PERSONAS

    at = _app()
    switch = at.selectbox(key="m3_user_switch")
    assert switch.options[0] == f"Ola · {DEMO_PERSONAS['u_ola'].tag}"
    assert switch.options[1].startswith("Kuba · ")
    assert any(c.value == DEMO_PERSONAS["u_ola"].scenario for c in at.caption)   # scenariusz pod listą
    switch.set_value("u_kuba")
    _run(at)
    assert at.session_state[Keys.USER_ID] == "u_kuba" and at.query_params["user"] == "u_kuba"
    assert any(c.value == DEMO_PERSONAS["u_kuba"].scenario for c in at.caption)


# --------------------------------------------------------------------------- #
# M3-08: „ukryj / pokaż mnie wszędzie” w edycji profilu
# --------------------------------------------------------------------------- #

def test_hide_everywhere_is_not_undone_by_open_event_panel(ui_storage):
    """Panel z wydarzeniem (przełącznik M5) jest otwarty obok edycji -> zmiana nie może zostać cofnięta."""
    event_id = "e_jazz_alchemia"
    at = _app(**{Keys.VIEW: View.PROFILE_EDIT, Keys.SELECTED_EVENT_ID: event_id})
    at.button(key="m3_priv_hide").click()
    _run(at)
    assert any("Ukryto Cię" in t.value for t in at.toast)
    _run(at)                                                           # kolejny rerun też niczego nie cofa
    assert not any(a.open_to_meet for a in ui_storage.list_user_attendance(DEMO_USER_ID))
    assert at.button(key="m3_priv_hide").disabled and not at.button(key="m3_priv_show").disabled

    at.session_state[Keys.SELECTED_EVENT_ID] = event_id               # ponowne otwarcie wydarzenia
    _run(at)
    assert at.toggle(key=f"m5_open_{DEMO_USER_ID}_{event_id}").value is False
    assert not ui_storage.get_attendance(DEMO_USER_ID, event_id).open_to_meet

    at.button(key="m3_priv_show").click()
    _run(at)
    assert all(a.open_to_meet for a in ui_storage.list_user_attendance(DEMO_USER_ID))


def test_onboarding_has_no_visibility_section(ui_storage):
    at = _start_onboarding(_app())
    assert not [b for b in at.button if b.key in ("m3_priv_hide", "m3_priv_show")]
