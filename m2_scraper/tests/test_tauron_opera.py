"""M2-07 — źródła uzupełniające: TAURON Arena (REST API) i Opera Krakowska (JSON repertuaru + strona spektaklu)."""

from datetime import date, datetime

from m2_scraper.sources.opera import (
    REPERTOIRE_URL,
    OperaSource,
    build_events,
    parse_repertoire,
    parse_spectacle,
)
from m2_scraper.sources.tauron import API_URL, TauronSource, parse_events
from m2_scraper.tests.conftest import FakeHttp, read_fixture
from shared.mock_data import KRAKOW_VENUES
from shared.models import Category

TODAY = date(2026, 10, 3)
HORIZON = date(2026, 11, 2)
FAUST_URL = "https://opera.krakow.pl/spektakle/faust"


def test_tauron_parse_events_categories_tags_and_horizon():
    events = parse_events(read_fixture("tauron_events.json"), TODAY, HORIZON)
    by_title = {e.title: e for e in events}
    assert "Korn" not in by_title                                    # 17.11 — poza horyzontem
    run = by_title["12. PKO Cracovia Półmaraton Królewski"]
    assert run.category == Category.SPORT and "bieganie" in run.tags
    assert run.start == datetime(2026, 10, 11, 10, 0) and run.end == datetime(2026, 10, 11, 19, 0)
    hack = by_title["HackYeah 2026"]
    assert hack.category == Category.MEETUP and "technologia" in hack.tags and "bieganie" not in hack.tags
    assert by_title["Targi Pracy i Przedsiębiorczości"].price_pln == 0    # "wstęp bezpłatny", nie pensja
    assert by_title["Polska Noc Kabaretowa 2026"].tags == ["stand-up"]
    tauron = KRAKOW_VENUES["tauron"]
    assert all((e.lat, e.lon) == (tauron.lat, tauron.lon) and e.source == "scraper:tauron" for e in events)
    assert len({e.id for e in events}) == len(events)                # 2 dni HackYeah = 2 różne ID
    assert all(len(e.description) <= 600 for e in events)


def test_tauron_source_offline():
    http = FakeHttp({API_URL.format(page=1): "tauron_events.json"})
    assert len(TauronSource(http, today=TODAY).fetch()) == 6
    assert http.requested == [API_URL.format(page=1)]                # total_pages=1 -> bez strony 2


def test_opera_parse_repertoire_ignores_injected_script():
    perfs = parse_repertoire(read_fixture("opera_repertuar_2026_10.json"))   # <script> przed i po JSON
    assert len(perfs) == 17
    faust = [p for p in perfs if p.title == "Faust"]
    assert faust[0].start == datetime(2026, 10, 16, 18, 30)
    assert faust[0].url == FAUST_URL and faust[0].type == "Opera" and faust[0].stage == "Duża Scena"


def test_opera_parse_spectacle_price_and_facts():
    spec = parse_spectacle(read_fixture("opera_spektakl_faust.html"))
    assert spec.price_pln == 100.0                                   # najtańsza kategoria (balkon)
    assert spec.composer == "Charles Gounod"
    assert spec.image_url and spec.image_url.startswith("https://opera.krakow.pl/")


def test_opera_build_events_skips_canceled_and_past():
    perfs = parse_repertoire(read_fixture("opera_repertuar_2026_10.json"))
    perfs.append(perfs[0].__class__(**{**perfs[0].__dict__, "start": datetime(2026, 10, 25, 18, 0),
                                       "canceled": True}))
    events = build_events(perfs, {FAUST_URL: parse_spectacle(read_fixture("opera_spektakl_faust.html"))},
                          date(2026, 10, 10), HORIZON)
    assert all(e.start >= datetime(2026, 10, 10) for e in events)
    assert not any(e.start == datetime(2026, 10, 25, 18, 0) for e in events)
    faust = [e for e in events if e.title == "Faust"]
    assert len(faust) == 7 and len({e.id for e in faust}) == 7
    assert all(e.category == Category.MUSIC and "opera" in e.tags and e.price_pln == 100.0 for e in faust)
    assert faust[0].description == "Opera · Charles Gounod · Duża Scena Opery Krakowskiej · czas trwania: 3 godziny 40 minut, 2 przerwy"
    assert faust[0].venue == "Opera Krakowska — Duża Scena"


def test_opera_source_offline_fetches_each_spectacle_once():
    pages = {REPERTOIRE_URL.format(year=2026, month=10): "opera_repertuar_2026_10.json",
             REPERTOIRE_URL.format(year=2026, month=11): "opera_repertuar_2026_10.json",   # brak listopada w fixture
             FAUST_URL: "opera_spektakl_faust.html"}
    http = FakeHttp(pages)
    events = OperaSource(http, today=TODAY).fetch()                  # pozostałe spektakle: brak strony -> bez ceny
    assert http.requested.count(FAUST_URL) == 1
    assert len({e.id for e in events}) == len(events) == 17
