"""Fixtury testów M2: testy działają WYŁĄCZNIE offline (fixture HTML) i nigdy nie dotykają data/."""

from __future__ import annotations

import json
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


@pytest.fixture(autouse=True)
def _isolated_geocoder(monkeypatch, tmp_path):
    """Domyślny geokoder w testach: cache w tmp_path, Nominatim niedozwolony (nigdy data/cache)."""
    from m2_scraper import geocode

    monkeypatch.setattr(geocode, "_default", geocode.Geocoder(tmp_path / "geocode.json", http=FakeGeoHttp({})))


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


class FakeGeoHttp:
    """Udawany Nominatim: zapytanie (parametr q) -> lista wyników [(lat, lon)]; robots.txt sterowany flagą."""

    def __init__(self, results: dict[str, list[tuple[float, float]]], *, allowed: bool = False,
                 fail: bool = False):
        self.results = results
        self.is_allowed = allowed
        self.fail = fail
        self.queries: list[str] = []

    def allowed(self, url: str) -> bool:
        return self.is_allowed

    def get_text(self, url: str, max_age_s: float | None = None) -> str:
        from urllib.parse import parse_qs, urlsplit

        query = parse_qs(urlsplit(url).query)["q"][0]
        self.queries.append(query)
        if self.fail:
            raise ConnectionError("brak sieci")
        return json.dumps([{"lat": str(lat), "lon": str(lon)} for lat, lon in self.results.get(query, [])])
