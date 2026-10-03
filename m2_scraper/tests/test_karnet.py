"""M2-02 — źródło Karnet: parsery listy/szczegółów i budowa eventów na zapisanym HTML (offline)."""

from datetime import date, datetime

import pytest

from m2_scraper.sources.karnet import (
    BASE_URL,
    LIST_URL,
    KarnetSource,
    build_events,
    parse_detail,
    parse_listing,
    split_location,
)
from m2_scraper.tests.conftest import FakeHttp, read_fixture
from shared.models import Category, is_in_krakow

TODAY = date(2026, 10, 3)        # dzień pobrania fixture
DIGGER_URL = BASE_URL + "/64992-krakow-digger-pokazy-przedpremierowe"


def test_parse_listing_cards_and_pagination():
    cards, has_next = parse_listing(read_fixture("karnet_list_p5.html"))
    assert len(cards) == 12 and has_next
    sbb = next(c for c in cards if "SBB" in c.title)
    assert sbb.url == BASE_URL + "/64519-krakow-sbb-skrzek-anthimos-piotrowski-w-studio"
    assert sbb.type == "Muzyka rozrywkowa"
    assert sbb.location == "Klub Studio, ul. Budryka 4"
    assert sbb.date_text == "03.10.2026, 20:00"
    assert sbb.lat is not None and is_in_krakow(sbb.lat, sbb.lon)
    assert all(c.url.startswith(BASE_URL + "/") for c in cards)


def test_parse_listing_handles_missing_location_and_coords():
    cards, _ = parse_listing(read_fixture("karnet_list_p1.html"))
    assert len(cards) == 12
    assert any(c.location == "" for c in cards)                       # "Dni Twierdzy Kraków" bez miejsca
    assert any(c.type == "W gminach Metropolii" for c in cards)


def test_parse_detail_multiple_dates_price_and_place():
    d = parse_detail(read_fixture("karnet_detail_digger.html"))
    assert d.title == "Digger. Pokazy przedpremierowe"
    assert d.type == "Pokazy filmowe"
    assert d.dates == ["sobota, 3 października 2026, 20:45", "niedziela, 4 października 2026, 18:00"]
    assert d.dates_total == 3                                          # + przeterminowany piątek
    assert d.places[0].name == "Kino Pod Baranami" and d.places[0].address == "Rynek Główny 27"
    assert "31 zł" in d.info and "26 zł" in d.info
    assert d.ticket_url == "https://rezerwacja.kinopodbaranami.pl/"
    assert d.description.startswith("Digger to niezwykle aktualna satyra")
    assert "materiały organizatora" not in d.description
    assert "Hüller, Riz Ahmed" in d.description                        # bez spacji przed przecinkiem


def test_parse_detail_date_range_and_two_places():
    d = parse_detail(read_fixture("karnet_detail_jazz_juniors.html"))
    assert d.dates == ["czwartek, 1 października 2026 - niedziela, 4 października 2026"]
    assert [p.name for p in d.places][:2] == ["Cricoteka Ośrodek Dokumentacji Sztuki Tadeusza Kantora",
                                              "Filharmonia Krakowska"]


@pytest.mark.parametrize("text, expected", [
    ("Alchemia, ul. Estery 5", ("Alchemia", "ul. Estery 5")),
    ("Kino Pod Baranami, Rynek Główny 27", ("Kino Pod Baranami", "Rynek Główny 27")),
    ("Teatr Łaźnia Nowa, os. Szkolne 25", ("Teatr Łaźnia Nowa", "os. Szkolne 25")),
    ("Muzeum, Oddział Rynek, ul. Rynek 1", ("Muzeum, Oddział Rynek", "ul. Rynek 1")),
    ("Bulwary Wiślane", ("Bulwary Wiślane", "")),
    ("", ("", "")),
])
def test_split_location(text, expected):
    assert split_location(text) == expected


def _card(cards_fixture: str, url: str):
    cards, _ = parse_listing(read_fixture(cards_fixture))
    return next(c for c in cards if c.url == url)


def test_build_events_one_event_per_future_showing():
    card = _card("karnet_list_p5.html", DIGGER_URL)
    detail = parse_detail(read_fixture("karnet_detail_digger.html"))
    events = build_events(card, detail, TODAY, date(2026, 10, 17))
    assert [e.start for e in events] == [datetime(2026, 10, 3, 20, 45), datetime(2026, 10, 4, 18, 0)]
    assert len({e.id for e in events}) == 2                            # osobne ID dla każdego seansu
    e = events[0]
    assert e.source == "scraper:karnet" and e.id.startswith("ev_")
    assert e.venue == "Kino Pod Baranami" and e.address == "Rynek Główny 27, Kraków"
    assert e.url == DIGGER_URL and e.image_url
    assert is_in_krakow(e.lat, e.lon)
    # determinizm: ten sam HTML -> te same ID (deduplikacja przy ponownym uruchomieniu)
    assert [x.id for x in build_events(card, detail, TODAY, date(2026, 10, 17))] == [x.id for x in events]


def test_build_events_normalizes_category_tags_and_price():
    card = _card("karnet_list_p5.html", DIGGER_URL)
    e = build_events(card, parse_detail(read_fixture("karnet_detail_digger.html")), TODAY, TODAY)[0]
    assert e.category == Category.CINEMA
    assert "kino" in e.tags
    assert e.price_pln == 31.0                                         # "31 zł (normalny) 26 zł (ulgowy)"

    sbb_url = BASE_URL + "/64519-krakow-sbb-skrzek-anthimos-piotrowski-w-studio"
    sbb = build_events(_card("karnet_list_p5.html", sbb_url), parse_detail(read_fixture("karnet_detail_sbb.html")),
                       TODAY, TODAY)[0]
    assert sbb.category == Category.MUSIC and "rock" in sbb.tags      # "rocka progresywnego"

    alicja_url = BASE_URL + "/61062-krakow-alicja-w-krainie-czarow-teatr-groteska"
    cards, _ = parse_listing(read_fixture("karnet_list_p5.html"))
    alicja = build_events(next(c for c in cards if c.url == alicja_url),
                          parse_detail(read_fixture("karnet_detail_alicja.html")), TODAY, date(2026, 10, 10))
    assert len(alicja) == 6 and all(a.category == Category.THEATRE and "teatr" in a.tags for a in alicja)


def test_build_events_respects_horizon_and_card_fallback():
    card = _card("karnet_list_p5.html", DIGGER_URL)
    detail = parse_detail(read_fixture("karnet_detail_digger.html"))
    assert len(build_events(card, detail, TODAY, TODAY)) == 1          # tylko dzisiejszy seans
    only_card = build_events(card, None, TODAY, TODAY)                 # szczegóły niedostępne
    assert len(only_card) == 1 and only_card[0].start == datetime(2026, 10, 3, 20, 45)


def test_karnet_source_fetch_offline_with_fake_http():
    pages = {
        LIST_URL.format(page=1): "karnet_list_p1.html",
        LIST_URL.format(page=2): "karnet_list_p5.html",
        DIGGER_URL: "karnet_detail_digger.html",
        BASE_URL + "/64786-krakow-jazz-juniors-2026": "karnet_detail_jazz_juniors.html",
        BASE_URL + "/64519-krakow-sbb-skrzek-anthimos-piotrowski-w-studio": "karnet_detail_sbb.html",
    }
    http = FakeHttp(pages)
    events = KarnetSource(http, days=0, today=TODAY).fetch()
    # strona 2 zawiera karty z 4.10 -> poza horyzontem -> crawl się kończy, nie prosi o stronę 3
    assert LIST_URL.format(page=3) not in http.requested
    assert len(events) >= 15
    assert all(is_in_krakow(e.lat, e.lon) for e in events)
    assert all(e.source == "scraper:karnet" for e in events)
    assert not any("Rybn" in e.title for e in events)                 # "W gminach Metropolii" pominięte
    titles = {e.title for e in events}
    assert {"Jazz Juniors 2026", "Digger. Pokazy przedpremierowe"} <= titles
    assert len({e.id for e in events}) == len(events)
