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
    """Tabela sandboxa = recommend_events z wagami z suwaków. Bez tytułów na sztywno: nowa baza
    plikowa może zawierać też prawdziwe eventy ze snapshotu M2."""
    from m4_matching.engine import REC_WEIGHTS, recommend_events
    from shared.storage import get_storage

    store = get_storage()                                             # ta sama baza, co w sandboxie
    ola = store.get_user("u_ola")

    def titles(weights) -> list[str]:
        return [r.event.title for r in recommend_events(store, ola, weights=weights)]

    def table() -> list[str]:
        return list(sandbox.dataframe[1].value["event"])

    tags_only = {**REC_WEIGHTS, "social": 0.0}
    assert titles(None) != titles(tags_only)                          # suwak ma realny wpływ
    assert table() == titles(None)
    sandbox.slider(key="m4_rw_social").set_value(0.0)
    sandbox.run()
    assert not sandbox.exception, sandbox.exception
    assert table() == titles(tags_only)
