"""M4-02 DoD: „zmiana wagi zmienia ranking w sandboxie” — sandbox sterowany przez AppTest."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from shared.storage import Storage

SANDBOX = Path(__file__).resolve().parents[1] / "sandbox.py"


@pytest.fixture
def sandbox(tmp_path, monkeypatch) -> AppTest:
    # Ten sam wzorzec co tests/test_sandboxes_smoke.py: izolowana baza zamiast data/app.db.
    monkeypatch.setattr("shared.storage._default_storage", Storage(tmp_path / "m4_sandbox.db"))
    at = AppTest.from_file(str(SANDBOX), default_timeout=30).run()
    assert not at.exception, at.exception
    return at


def _column(at: AppTest, name: str) -> list:
    return list(at.dataframe[0].value[name])


def test_sandbox_opens_on_demo_scenario(sandbox: AppTest):
    assert sandbox.selectbox(key="m4_user").value == "u_ola"
    assert sandbox.selectbox(key="m4_event").value == "e_jazz_alchemia"
    assert _column(sandbox, "osoba") == ["Bartek", "Natalia", "Kuba", "Tomek"]


def test_weight_sliders_change_ranking(sandbox: AppTest):
    for name in ("co_attendance", "event_fit", "status"):
        sandbox.slider(key=f"m4_w_{name}").set_value(0.0)
    sandbox.run()
    assert not sandbox.exception, sandbox.exception
    assert _column(sandbox, "osoba")[0] == "Natalia"                  # same tagi IDF
    assert _column(sandbox, "miejsce przy WEIGHTS")[0] == 2            # przy WEIGHTS była druga


def test_rec_weight_sliders_change_recommendations(sandbox: AppTest):
    def top_rec() -> str:
        return list(sandbox.dataframe[1].value["event"])[0]

    assert top_rec() == "Oprowadzanie kuratorskie: Wyspiański"       # tagi + 3 podobne osoby
    sandbox.slider(key="m4_rw_social").set_value(0.0)
    sandbox.run()
    assert not sandbox.exception, sandbox.exception
    assert top_rec() == "Przedpremierowy pokaz + Q&A z reżyserką"     # same tagi: pełne pokrycie „kino”
