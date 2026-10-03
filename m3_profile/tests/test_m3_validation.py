"""M3-03 — validate_profile: reguły (imię 1–60, bio ≤ 280, 3–10 tagów) i normalizacja."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from m3_profile.validation import BIO_MAX, NAME_MAX, TAG_MAX_LEN, TAGS_MAX, TAGS_MIN, validate_profile
from shared.models import User

ROOT = Path(__file__).resolve().parents[2]
TAGS_OK = ["jazz", "kino", "kawa"]


def test_valid_profile_has_no_errors_and_is_normalized():
    clean, errors = validate_profile("  Ola   Kowalska ", "  Lubię jazz.  \r\n\r\n\r\n  Szukam ekipy. ", [
        "#Jazz", " jazz ", "Sztuka  Współczesna", "KINO", "",
    ])
    assert errors == {}
    assert clean == {
        "name": "Ola Kowalska",
        "bio": "Lubię jazz.\n\n  Szukam ekipy.",
        "tags": ["jazz", "sztuka współczesna", "kino"],
    }


def test_clean_values_fit_user_model():
    clean, errors = validate_profile("Ola", "", TAGS_OK)
    assert not errors
    assert User(id="u_x", name="X").copy_with(**clean).tags == TAGS_OK


@pytest.mark.parametrize("name", ["", "   ", "\n\t"])
def test_name_is_required(name):
    _, errors = validate_profile(name, "", TAGS_OK)
    assert "imię" in errors["name"].lower()


def test_name_length_limit_counts_normalized_text():
    assert "name" not in validate_profile("A" * NAME_MAX, "", TAGS_OK)[1]
    assert "name" not in validate_profile(" " * 10 + "A" * NAME_MAX + " " * 10, "", TAGS_OK)[1]
    _, errors = validate_profile("A" * (NAME_MAX + 1), "", TAGS_OK)
    assert f"{NAME_MAX}" in errors["name"] and f"{NAME_MAX + 1}" in errors["name"]


def test_bio_is_optional_but_limited():
    assert validate_profile("Ola", "", TAGS_OK)[1] == {}
    assert "bio" not in validate_profile("Ola", "x" * BIO_MAX, TAGS_OK)[1]
    _, errors = validate_profile("Ola", "x" * (BIO_MAX + 1), TAGS_OK)
    assert str(BIO_MAX) in errors["bio"]


@pytest.mark.parametrize("tags, ok", [
    ([], False),
    (["jazz", "kino"], False),
    (["jazz", "JAZZ", "#jazz", "kino"], False),            # duplikaty po normalizacji się nie liczą
    (TAGS_OK, True),
    ([f"tag {i}" for i in range(TAGS_MAX)], True),
    ([f"tag {i}" for i in range(TAGS_MAX + 1)], False),
])
def test_tag_count_between_3_and_10(tags, ok):
    _, errors = validate_profile("Ola", "", tags)
    assert ("tags" not in errors) is ok


def test_tag_messages_say_what_to_do():
    assert f"co najmniej {TAGS_MIN}" in validate_profile("Ola", "", ["jazz"])[1]["tags"]
    assert "brakuje 2" in validate_profile("Ola", "", ["jazz"])[1]["tags"]
    assert "usuń 2" in validate_profile("Ola", "", [f"t{i}" for i in range(TAGS_MAX + 2)])[1]["tags"]


def test_custom_tag_too_long_is_rejected():
    long_tag = "a" * (TAG_MAX_LEN + 1)
    _, errors = validate_profile("Ola", "", [*TAGS_OK, long_tag])
    assert str(TAG_MAX_LEN) in errors["tags"] and long_tag in errors["tags"]


def test_all_errors_reported_at_once():
    _, errors = validate_profile("", "x" * (BIO_MAX + 1), [])
    assert set(errors) == {"name", "bio", "tags"}


def test_none_inputs_do_not_crash():
    clean, errors = validate_profile(None, None, None)   # type: ignore[arg-type]
    assert clean == {"name": "", "bio": "", "tags": []} and set(errors) == {"name", "tags"}


def test_validation_module_does_not_import_streamlit():
    code = "import sys, m3_profile.validation; sys.exit('streamlit' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], cwd=ROOT).returncode == 0
