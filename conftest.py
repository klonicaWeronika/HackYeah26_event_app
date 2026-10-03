"""Wspólne fixtury pytest dla wszystkich modułów (izolowana baza w RAM z mockami)."""

import pytest

from shared.mock_data import DEMO_USER_ID
from shared.models import User
from shared.storage import Storage


@pytest.fixture
def storage() -> Storage:
    """Świeża baza :memory: z mockami — każdy test dostaje własną, testy się nie widzą."""
    store = Storage(":memory:")
    yield store
    store.close()


@pytest.fixture
def empty_storage() -> Storage:
    store = Storage(":memory:", seed_if_empty=False)
    yield store
    store.close()


@pytest.fixture
def demo_user(storage: Storage) -> User:
    user = storage.get_user(DEMO_USER_ID)
    assert user is not None
    return user
