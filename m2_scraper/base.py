"""
M2 — wspólne klocki dla źródeł wydarzeń.

Każde źródło implementuje protokół `EventSource`: `fetch() -> list[Event]`.
Źródło NIE zapisuje do bazy — robi to pipeline w run.py (łatwe testy, dry-run).
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import certifi
import requests

from shared.models import Event
from shared.storage import PROJECT_ROOT

log = logging.getLogger(__name__)

HTTP_CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "http"
CA_BUNDLE_PATH = PROJECT_ROOT / "data" / "cache" / "ca_bundle.pem"
CERTS_DIR = Path(__file__).resolve().parent / "certs"
USER_AGENT = "Meevent-HackYeah-demo/0.1 (hackathon project; contact: team)"
ROBOTS_TTL_S = 24 * 3600


class EventSource(Protocol):
    name: str                              # np. "karnet" -> Event.source = "scraper:karnet"

    def fetch(self) -> list[Event]: ...


class RobotsDisallowed(RuntimeError):
    """robots.txt zabrania pobrania adresu — źródło musi to uszanować."""


def ca_bundle() -> str:
    """certifi + certyfikaty pośrednie z m2_scraper/certs/ (serwery wysyłające niepełny łańcuch TLS).

    Weryfikacja TLS zostaje włączona — dokładamy tylko publiczne certyfikaty CA, których serwer nie wysłał.
    """
    extra = sorted(CERTS_DIR.glob("*.pem"))
    if not extra:
        return certifi.where()
    content = Path(certifi.where()).read_text(encoding="ascii")
    content += "".join("\n" + pem.read_text(encoding="ascii") for pem in extra)
    if not CA_BUNDLE_PATH.exists() or CA_BUNDLE_PATH.read_text(encoding="ascii") != content:
        CA_BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CA_BUNDLE_PATH.write_text(content, encoding="ascii")
    return str(CA_BUNDLE_PATH)


class PoliteHttp:
    """requests + User-Agent + robots.txt + opóźnienie między zapytaniami + cache odpowiedzi na dysku.

    Cache sprawia, że po pierwszym pobraniu pracujesz offline i nie męczysz serwisu
    przy każdym uruchomieniu parsera. `max_age_s` w `get_text` = po ilu sekundach odświeżyć wpis
    (None = nigdy). Gdy sieć nie działa, a w cache jest stara kopia — zwracamy ją (demo offline).
    Zmienna środowiskowa `M2_OFFLINE=1` wyłącza sieć całkowicie (tylko cache).
    """

    def __init__(self, delay_s: float = 1.0, use_cache: bool = True, timeout_s: float = 15.0):
        self.delay_s = max(delay_s, 1.0)          # zasada zespołu: nigdy szybciej niż 1 zapytanie/s
        self.use_cache = use_cache
        self.timeout_s = timeout_s
        self.offline = os.environ.get("M2_OFFLINE") == "1"
        self.requests_made = 0
        self._last_request = 0.0
        self._robots: dict[str, RobotFileParser] = {}
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self._session.verify = ca_bundle()

    @staticmethod
    def cache_file(url: str) -> Path:
        return HTTP_CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".html")

    def _read_cache(self, url: str, max_age_s: float | None) -> tuple[str | None, bool]:
        """(treść, czy_świeża)."""
        path = self.cache_file(url)
        if not self.use_cache or not path.exists():
            return None, False
        fresh = max_age_s is None or (time.time() - path.stat().st_mtime) < max_age_s
        return path.read_text(encoding="utf-8"), fresh

    def _write_cache(self, url: str, text: str) -> None:
        if self.use_cache:
            path = self.cache_file(url)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def _get(self, url: str) -> requests.Response:
        if self.offline:
            raise ConnectionError(f"M2_OFFLINE=1, brak w cache: {url}")
        wait = self.delay_s - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            response = self._session.get(url, timeout=self.timeout_s)
        finally:
            self._last_request = time.monotonic()
            self.requests_made += 1
        if "charset" not in response.headers.get("Content-Type", "").lower():
            response.encoding = "utf-8"           # requests domyślnie zgaduje ISO-8859-1 -> krzaki w PL
        return response

    def _robots_parser(self, url: str) -> RobotFileParser:
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        if robots_url not in self._robots:
            text, fresh = self._read_cache(robots_url, ROBOTS_TTL_S)
            if not fresh:
                response = self._get(robots_url)
                if response.status_code in (401, 403):        # semantyka jak w urllib.robotparser
                    text = f"# HTTP {response.status_code}\nUser-agent: *\nDisallow: /\n"
                elif 400 <= response.status_code < 500:
                    text = f"# HTTP {response.status_code} — brak robots.txt\n"
                else:
                    response.raise_for_status()
                    text = response.text
                self._write_cache(robots_url, text)
            parser = RobotFileParser(robots_url)
            parser.parse(text.splitlines())
            self._robots[robots_url] = parser
        return self._robots[robots_url]

    def allowed(self, url: str) -> bool:
        return self._robots_parser(url).can_fetch(USER_AGENT, url)

    def get_text(self, url: str, max_age_s: float | None = None) -> str:
        cached, fresh = self._read_cache(url, max_age_s)
        if cached is not None and fresh:
            return cached
        try:
            if not self.allowed(url):
                raise RobotsDisallowed(url)
            response = self._get(url)
            response.raise_for_status()
        except (requests.RequestException, ConnectionError):
            if cached is not None:
                log.warning("Sieć niedostępna, używam starszej kopii z cache: %s", url)
                return cached
            raise
        self._write_cache(url, response.text)
        return response.text
