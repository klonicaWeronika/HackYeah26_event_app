"""M3 — testy UI profilu przez AppTest (izolowana baza w tmp_path, nigdy data/app.db)."""

from __future__ import annotations

import io

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from shared.mock_data import DEMO_USER_ID
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
    assert 'src="data:image/jpeg;base64,' in _preview_html(editor)
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
    (b"to nie jest obraz", "uszkodzony"),
    (b"\xff" * (5 * 1024 * 1024 + 1), "5 MB"),
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
    assert "<img" not in _preview_html(editor)                       # podgląd: inicjały
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
    before = {m.user.id: m.score for m in match_for_event(ui_storage, ui_storage.get_user(DEMO_USER_ID), event_id)}
    _field(editor, "multiselect", "tags").set_value(["bieganie", "rower", "joga"])
    _save(editor)
    after = {m.user.id: m.score for m in match_for_event(ui_storage, ui_storage.get_user(DEMO_USER_ID), event_id)}
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
