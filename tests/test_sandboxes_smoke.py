"""Każdy sandbox modułu musi się uruchamiać (izolowana baza, bez przeglądarki)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from shared.storage import Storage

ROOT = Path(__file__).resolve().parents[1]   # Streamlit 1.65: AppTest.from_file liczy ścieżkę względną od pliku testu, nie od cwd
SANDBOXES = ["m2_scraper/sandbox.py", "m3_profile/sandbox.py", "m4_matching/sandbox.py", "m5_chat/sandbox.py"]


@pytest.mark.parametrize("path", SANDBOXES)
def test_sandbox_runs(path, tmp_path, monkeypatch):
    monkeypatch.setattr("shared.storage._default_storage", Storage(tmp_path / "sandbox.db"))
    at = AppTest.from_file(str(ROOT / path), default_timeout=30).run()
    assert not at.exception, at.exception
