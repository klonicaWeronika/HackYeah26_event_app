"""
M2 — wspólne klocki dla źródeł wydarzeń.

Każde źródło implementuje protokół `EventSource`: `fetch() -> list[Event]`.
Źródło NIE zapisuje do bazy — robi to pipeline w run.py (łatwe testy, dry-run).
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Protocol

import requests

from shared.models import Event
from shared.storage import PROJECT_ROOT

HTTP_CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "http"
USER_AGENT = "KRKRazem-HackYeah-demo/0.1 (hackathon project; contact: team)"


class EventSource(Protocol):
    name: str                              # np. "karnet" -> Event.source = "scraper:karnet"

    def fetch(self) -> list[Event]: ...


class PoliteHttp:
    """requests + User-Agent + opóźnienie między zapytaniami + cache HTML na dysku.

    Cache sprawia, że po pierwszym pobraniu pracujesz offline i nie męczysz serwisu
    przy każdym uruchomieniu parsera.
    """

    def __init__(self, delay_s: float = 1.0, use_cache: bool = True, timeout_s: float = 15.0):
        self.delay_s = delay_s
        self.use_cache = use_cache
        self.timeout_s = timeout_s
        self._last_request = 0.0
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    def get_text(self, url: str) -> str:
        cache_file = HTTP_CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".html")
        if self.use_cache and cache_file.exists():
            return cache_file.read_text(encoding="utf-8")

        wait = self.delay_s - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        response = self._session.get(url, timeout=self.timeout_s)
        self._last_request = time.monotonic()
        response.raise_for_status()

        if self.use_cache:
            Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(response.text, encoding="utf-8")
        return response.text
