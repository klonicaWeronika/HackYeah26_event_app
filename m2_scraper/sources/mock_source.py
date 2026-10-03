"""Źródło referencyjne: zwraca mocki (wzorzec kształtu danych + plan awaryjny na demo)."""

from __future__ import annotations

from shared.mock_data import build_mock_dataset
from shared.models import Event


class MockSource:
    name = "mock"

    def fetch(self) -> list[Event]:
        return build_mock_dataset().events
