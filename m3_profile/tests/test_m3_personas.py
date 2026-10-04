"""M3-09 — persony demo w przełączniku „Zaloguj jako”."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from m3_profile.personas import (
    DEMO_PERSONAS, persona_label, persona_scenario, sort_for_switcher, switcher_labels,
)
from shared.mock_data import DEMO_USER_ID, build_mock_dataset
from shared.models import User

ROOT = Path(__file__).resolve().parents[2]


def test_every_persona_is_a_mock_user_and_demo_user_comes_first():
    mock_ids = {u.id for u in build_mock_dataset().users}
    assert set(DEMO_PERSONAS) <= mock_ids, "persona bez użytkownika w mockach (zmienione ID?)"
    assert next(iter(DEMO_PERSONAS)) == DEMO_USER_ID


def test_persona_texts_fit_the_narrow_options_popover():
    assert all(len(p.tag) <= 14 and len(p.scenario) <= 90 for p in DEMO_PERSONAS.values())


def test_label_has_scenario_for_personas_and_plain_name_otherwise():
    assert persona_label(User(id="u_ola", name="Ola")) == f"Ola · {DEMO_PERSONAS['u_ola'].tag}"
    assert persona_label(User(id="u_abc123", name="Ewa")) == "Ewa"
    assert persona_scenario("u_ola") and persona_scenario("u_abc123") is None


def test_switcher_labels_are_unique_for_same_names():
    """Selectbox znajduje wybór po etykiecie — dwie „Ewy” nie mogą mieć tej samej."""
    users = [User(id="u_ewa", name="Ewa"), User(id="u_bb74eeb16ba4", name="Ewa"), User(id="u_ola", name="Ola")]
    labels = switcher_labels(users)
    assert len(set(labels.values())) == len(users)
    assert labels["u_ola"] == persona_label(users[2])            # unikalne etykiety bez zmian
    assert labels["u_bb74eeb16ba4"] == "Ewa · #6ba4"


def test_sort_follows_demo_script_then_new_profiles_alphabetically():
    users = [User(id="u_new2", name="Zenek"), User(id="u_kuba", name="Kuba"),
             User(id="u_new1", name="adam"), User(id="u_ola", name="Ola")]
    assert [u.id for u in sort_for_switcher(users)] == ["u_ola", "u_kuba", "u_new1", "u_new2"]


def test_personas_module_does_not_import_streamlit():
    code = "import sys, m3_profile.personas; sys.exit('streamlit' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], cwd=ROOT).returncode == 0
