"""M2-03 — normalizacja: polskie daty, ceny, kategorie i tagi (testy tabelaryczne, offline)."""

from datetime import date, datetime

import pytest

from m2_scraper.normalize import extract_tags, find_price, map_category, parse_pl_datetime, parse_price, shorten
from shared.models import INTEREST_TAGS, Category

TODAY = date(2026, 10, 3)        # sobota
D = datetime


# (tekst ze źródła, oczekiwany start, oczekiwany koniec, czy podano godzinę)
DATE_CASES = [
    # lista Karnetu (fixture karnet_list_*.html)
    ("03.10.2026, 19:00", D(2026, 10, 3, 19, 0), None, True),
    ("04.10.2026, 11:00-16:00", D(2026, 10, 4, 11, 0), D(2026, 10, 4, 16, 0), True),
    ("01.09.2026, 09:00 - 31.12.2026", D(2026, 9, 1, 9, 0), D(2026, 12, 31, 23, 59), True),
    ("25.09.2026, 00:00 - 04.10.2026, 23:00", D(2026, 9, 25, 0, 0), D(2026, 10, 4, 23, 0), True),
    ("13.09.2026 - 13.11.2026", D(2026, 9, 13), D(2026, 11, 13, 23, 59), False),
    ("10.10.2026", D(2026, 10, 10), None, False),
    # strony szczegółów Karnetu (fixture karnet_detail_*.html)
    ("sobota, 3 października 2026, 20:45", D(2026, 10, 3, 20, 45), None, True),
    ("niedziela, 4 października 2026, 18:00", D(2026, 10, 4, 18, 0), None, True),
    ("czwartek, 1 października 2026 - niedziela, 4 października 2026", D(2026, 10, 1), D(2026, 10, 4, 23, 59), False),
    ("1.10.2026, godz. 19:00", D(2026, 10, 1, 19, 0), None, True),
    # skróty, dni tygodnia, brak roku -> najbliższa przyszła data
    ("pt, 10 paź, 19:00", D(2026, 10, 10, 19, 0), None, True),
    ("sob 3 paź 22:00-02:00", D(2026, 10, 3, 22, 0), None, True),       # koniec po północy -> brak końca
    ("10 października", D(2026, 10, 10), None, False),
    ("2 stycznia", D(2027, 1, 2), None, False),
    ("1 paź", D(2027, 10, 1), None, False),                             # 1.10 już minął -> za rok
    ("15 LISTOPADA 2026 20:00", D(2026, 11, 15, 20, 0), None, True),
    # zakresy
    ("10–12.10", D(2026, 10, 10), D(2026, 10, 12, 23, 59), False),
    ("10-12 października 2026", D(2026, 10, 10), D(2026, 10, 12, 23, 59), False),
    ("30.12 - 2.01", D(2026, 12, 30), D(2027, 1, 2, 23, 59), False),
    ("1–4.10", D(2026, 10, 1), D(2026, 10, 4, 23, 59), False),           # trwa -> ten rok, nie przyszły
    # sam miesiąc (Karnet: "październik 2026 - październik 2026")
    ("październik 2026 - październik 2026", D(2026, 10, 1), D(2026, 10, 31, 23, 59), False),
    ("listopad 2026 - styczeń 2027", D(2026, 11, 1), D(2027, 1, 31, 23, 59), False),
]


@pytest.mark.parametrize("text, start, end, has_time", DATE_CASES)
def test_parse_pl_datetime(text, start, end, has_time):
    span = parse_pl_datetime(text, TODAY)
    assert span is not None, text
    assert (span.start, span.end, span.has_time) == (start, end, has_time)


@pytest.mark.parametrize("text", ["", "brak daty", "Termin wkrótce", "31.02.2026", "45.10.2026"])
def test_parse_pl_datetime_unparseable(text):
    assert parse_pl_datetime(text, TODAY) is None


PRICE_CASES = [
    ("wstęp wolny", 0.0),
    ("WSTĘP WOLNY", 0.0),
    ("Wstęp bezpłatny po wcześniejszej rejestracji", 0.0),
    ("bezpłatne", 0.0),
    ("wydarzenie darmowe", 0.0),
    ("od 40 zł", 40.0),
    ("Bilety od 59,99 zł", 59.99),
    ("31 zł (normalny) 26 zł (ulgowy)", 31.0),                           # fixture karnet_detail_digger
    ("bilety: 50/40 zł", 50.0),                                         # normalny/ulgowy
    ("60/40 zł", 60.0),
    ("40-110 zł", 40.0),
    ("Od 105 zł", 105.0),
    ("BILETY: 21 zł Dzieci uczestniczą w pokazie bezpłatnie.", 21.0),
    ("Wstęp wolny, wejściówki", 0.0),
    ("wstęp wolny (zapisy)", 0.0),
    ("40-60 zł", 40.0),
    ("40–60 zł", 40.0),
    ("120 PLN", 120.0),
    ("Bilety: 30 zł, dzieci do lat 3 wstęp wolny", 30.0),                # kwota > fraza o darmowym wstępie
    ("bilety 1 200 zł", 1200.0),
    ("", None),
    ("brak informacji o biletach", None),
    ("kup bilet", None),
]


@pytest.mark.parametrize("text, expected", PRICE_CASES)
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("info, description, expected", [
    ("", "Wynagrodzenie od 3000 zł brutto. Wstęp na targi bezpłatny.", 0.0),   # pensja != cena biletu
    ("", "Nagrody o łącznej wartości 10 000 zł! Bilety: 45 zł.", 45.0),
    ("", "Opłata startowa wynosi 80 zł.", 80.0),
    ("", "Pakiet VIP 2500 zł, bilety od 199 zł", 199.0),
    ("", "Koncert legendy rocka.", None),
    ("60/40 zł", "Wstęp wolny dla dzieci", 60.0),                       # pole z ceną ma pierwszeństwo
])
def test_find_price_uses_only_ticket_sentences(info, description, expected):
    assert find_price(info, description) == expected


@pytest.mark.parametrize("source_type, title, expected", [
    ("Spektakle teatralne", "Wesele", Category.THEATRE),
    ("Spektakle taneczne", "Jezioro", Category.THEATRE),
    ("Inne przedstawienia", "Klaun Feliks", Category.THEATRE),
    ("Muzyka rozrywkowa", "SBB w Studio", Category.MUSIC),
    ("Muzyka klubowa", "Digital Riot", Category.MUSIC),
    ("Inne koncerty", "Koncert", Category.MUSIC),
    ("Pokazy filmowe", "Digger", Category.CINEMA),
    ("Cykle filmowe", "Kino klasyki", Category.CINEMA),
    ("Wystawy czasowe", "Siła fotografii", Category.EXHIBITION),
    ("Festiwale i przeglądy filmowe", "Młode Horyzonty", Category.FESTIVAL),
    ("Festiwale teatralne", "Mała Boska Komedia", Category.FESTIVAL),
    ("Spacery i zwiedzanie", "Dni Twierdzy", Category.OUTDOOR),
    ("Widowiska plenerowe i happeningi", "Święto Ulicy", Category.OUTDOOR),
    ("Wydarzenia sportowe", "Półmaraton", Category.SPORT),
    ("Spotkania i wykłady literackie", "Spotkanie autorskie", Category.MEETUP),
    ("Wykłady, spacery i warsztaty artystyczne", "Warsztaty linorytu", Category.WORKSHOP),
    ("Pozostałe", "Edukacyjne wycieczki rowerowe", Category.SPORT),       # typ ogólny -> słowa kluczowe
    ("Pozostałe", "Coś zupełnie innego", Category.OTHER),
    ("Kabaret", "Polska Noc Kabaretowa", Category.OTHER),
    ("", "Degustacja win z Małopolski", Category.FOOD),
])
def test_map_category(source_type, title, expected):
    assert map_category(source_type, title) == expected


@pytest.mark.parametrize("text, expected", [
    ("SBB — legendy polskiego rocka progresywnego", {"rock"}),
    ("Jam session jazzowy w piwnicy", {"jazz"}),
    ("Koncert symfoniczny: Beethoven", {"klasyka"}),
    ("Faust — opera w 5 aktach", {"opera"}),
    ("Spektakl dla dzieci w Teatrze Groteska", {"teatr"}),
    ("Pokaz przedpremierowy filmu", {"kino"}),
    ("Wystawa fotografii reportażowej", {"fotografia"}),
    ("Spacer z przewodnikiem po Kazimierzu", {"spacery"}),
    ("Edukacyjne wycieczki rowerowe", {"rower"}),
    ("12. PKO Cracovia Półmaraton Królewski", {"bieganie"}),
    ("„Czaniecka Piątka” — bieg na 5 km", {"bieganie"}),
    ("Polska Noc Kabaretowa", {"stand-up"}),
    ("Spotkanie autorskie i premiera książki", {"literatura"}),
    ("Wieczór gier planszowych", {"planszówki"}),
    ("Warsztaty ceramiki", {"rękodzieło"}),
    ("Hackathon i AI w praktyce", {"technologia"}),
    ("Wiedźmin: Muzyka Kontynentu — koncert muzyki z gier wideo", {"gry wideo"}),
    ("Cracovia Music Festival", set()),                                  # 'Cracovia' to nie piłka nożna
    ("Winter Jazz", {"jazz"}),                                            # 'Winter' to nie wino
    ("24-godzinny maraton programowania", {"technologia"}),
])
def test_extract_tags_keywords(text, expected):
    assert expected <= set(extract_tags(text)), extract_tags(text)
    if not expected:
        assert extract_tags(text) == []


def test_extract_tags_marathon_needs_running_context():
    assert "bieganie" not in extract_tags("24-godzinny maraton programowania")   # HackYeah to nie bieg
    assert "bieganie" not in extract_tags("Maraton filmowy: trylogia")
    assert "bieganie" in extract_tags("Cracovia Maraton 2027")


def test_extract_tags_type_defaults_and_canonical():
    assert "teatr" in extract_tags("Wszystko, co najlepsze", source_type="Spektakle teatralne")
    assert "kino" in extract_tags("Najlepsza owsianka na świecie", source_type="Pokazy filmowe")
    assert "techno" in extract_tags("Digital Riot", source_type="Muzyka klubowa")
    for tags in (extract_tags("Wystawa malarstwa i rzeźby w galerii"), extract_tags("x", source_type="Kabaret")):
        assert tags and set(tags) <= set(INTEREST_TAGS)


def test_shorten_cuts_at_sentence():
    text = "Pierwsze zdanie jest tutaj. " * 40
    out = shorten(text, 100)
    assert len(out) <= 100 and out.endswith(".")
