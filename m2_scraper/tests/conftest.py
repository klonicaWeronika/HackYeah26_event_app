"""Fixtury testów M2: testy działają WYŁĄCZNIE offline (fixture HTML) i nigdy nie dotykają data/."""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Każda próba wyjścia do sieci w testach M2 = błąd (parsery testujemy na zapisanym HTML)."""
    def blocked(*args, **kwargs):
        raise RuntimeError("Sieć jest wyłączona w testach M2 — użyj fixture HTML")

    monkeypatch.setattr(requests.Session, "request", blocked)
    monkeypatch.setenv("M2_OFFLINE", "1")


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    """Zamiennik PoliteHttp: URL -> plik z fixtures; nieznany URL -> ConnectionError."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.requested: list[str] = []

    def get_text(self, url: str, max_age_s: float | None = None) -> str:
        self.requested.append(url)
        if url not in self.pages:
            raise ConnectionError(f"brak fixture dla {url}")
        return read_fixture(self.pages[url])
