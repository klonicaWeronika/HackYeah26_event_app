"""
M2 — normalizacja surowych pól ze źródeł:
polskie daty -> datetime, ceny -> price_pln, typ źródła -> Category, słowa kluczowe -> tagi.

Czyste funkcje (tekst -> dane), bez sieci i bez stanu — testowane tabelarycznie w tests/test_normalize.py.
Wszystkie datetime są NAIWNE (czas lokalny Europe/Warsaw), zgodnie z shared/models.py.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, time

from shared.models import Category, fold_text, normalize_tag

# Klucz = pierwsze 3 litery nazwy miesiąca bez ogonków (dopełniacz, mianownik i skróty mają wspólny prefiks).
_MONTHS = {
    "sty": 1, "lut": 2, "mar": 3, "kwi": 4, "maj": 5, "cze": 6,
    "lip": 7, "sie": 8, "wrz": 9, "paz": 10, "lis": 11, "gru": 12,
}

_TIME = r"(?P<{n}>\d{{1,2}}:\d{{2}})"
_TIME_RE = (
    r"(?:\s*,?\s*(?:godz\.?|g\.)?\s*" + _TIME.format(n="t1")
    + r"(?:\s*-\s*" + _TIME.format(n="t2") + r")?)?"
)
# "10-12.10[.2026]" / "10.10[.2026]"  albo  "10-12 października [2026]" / "10 paź"
_DATE_RE = re.compile(
    r"(?<![\d.])(?:(?P<d0>\d{1,2})\s*-\s*)?(?P<d>\d{1,2})"
    r"(?:\.(?P<m>\d{1,2})(?:\.(?P<y>\d{4}))?(?![\d])|\s+(?P<mon>[a-z]{3,})\.?(?:\s+(?P<y2>\d{4}))?)"
    + _TIME_RE
)
END_OF_DAY = time(23, 59)
DESCRIPTION_LIMIT = 600     # krótki opis + link do źródła (nie kopiujemy całych tekstów)


def clean_text(text: str) -> str:
    """Zbija białe znaki i usuwa spacje przed interpunkcją ('Hüller , Riz' -> 'Hüller, Riz')."""
    return re.sub(r"\s+([,.;:!?)])", r"\1", " ".join((text or "").split()))


def with_city(address: str, city: str = "Kraków") -> str:
    """'ul. Estery 5' -> 'ul. Estery 5, Kraków'; nie dubluje miasta ('ul. Krakowska 13' to wciąż ulica)."""
    address = (address or "").strip()
    if not address or re.search(r"\bkrakow\b", fold_text(address)):       # słowo "Kraków", nie "Krakowska"
        return address
    return f"{address}, {city}"


def shorten(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    """Skraca opis do ~limit znaków, najchętniej na końcu zdania."""
    text = clean_text(text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sentence_end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if sentence_end > limit // 2:
        return cut[:sentence_end + 1]
    return cut.rsplit(" ", 1)[0] + "…"


@dataclass(frozen=True)
class DateSpan:
    start: datetime
    end: datetime | None
    has_time: bool              # False = źródło podało tylko datę (start o 00:00)


@dataclass(frozen=True)
class _Point:
    day_from: int | None        # początek zakresu dni w tym samym miesiącu ("10-12.10")
    day: int
    month: int
    year: int | None
    t1: time | None
    t2: time | None


def _parse_time(value: str | None) -> time | None:
    if not value:
        return None
    hours, minutes = map(int, value.split(":"))
    if hours == 24 and minutes == 0:
        return END_OF_DAY
    return time(hours, minutes) if hours < 24 and minutes < 60 else None


def _points(text: str) -> list[_Point]:
    folded = fold_text(text).replace("–", "-").replace("—", "-")
    out: list[_Point] = []
    for m in _DATE_RE.finditer(folded):
        if m["mon"]:
            month = _MONTHS.get(m["mon"][:3])
            year = m["y2"]
        else:
            month = int(m["m"])
            year = m["y"]
        if not month or not 1 <= month <= 12 or not 1 <= int(m["d"]) <= 31:
            continue
        out.append(_Point(
            day_from=int(m["d0"]) if m["d0"] else None, day=int(m["d"]), month=month,
            year=int(year) if year else None, t1=_parse_time(m["t1"]), t2=_parse_time(m["t2"]),
        ))
    return out


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _nearest_future(month: int, day: int, today: date) -> date | None:
    """Brak roku w źródle -> najbliższa data >= dziś."""
    for year in (today.year, today.year + 1):
        d = _safe_date(year, month, day)
        if d and d >= today:
            return d
    return None


_MONTH_YEAR_RE = re.compile(r"(?<![a-z])([a-z]{3,})\s+(\d{4})(?!\d)")


def _parse_months_only(text: str) -> DateSpan | None:
    """'październik 2026 - listopad 2026' -> od 1. dnia pierwszego do ostatniego dnia ostatniego miesiąca."""
    months = [(int(y), _MONTHS[m[:3]]) for m, y in _MONTH_YEAR_RE.findall(fold_text(text)) if m[:3] in _MONTHS]
    if not months:
        return None
    (y1, m1), (y2, m2) = months[0], months[-1]
    start = datetime(y1, m1, 1)
    end = datetime.combine(date(y2, m2, calendar.monthrange(y2, m2)[1]), END_OF_DAY)
    return DateSpan(start, end, has_time=False) if end > start else None


def parse_pl_datetime(text: str, today: date | None = None) -> DateSpan | None:
    """Polski termin wydarzenia -> DateSpan. Rozumie m.in.:

    "03.10.2026, 19:00" · "04.10.2026, 11:00-16:00" · "13.09.2026 - 13.11.2026"
    "25.09.2026, 00:00 - 04.10.2026, 23:00" · "sobota, 3 października 2026, 20:45"
    "czwartek, 1 października 2026 - niedziela, 4 października 2026"
    Zakres bez godzin kończy się o 23:59 ostatniego dnia.
    """
    today = today or date.today()
    points = _points(text or "")
    if not points:
        return _parse_months_only(text or "")

    first, last = points[0], points[-1]
    if len(points) == 1 and first.day_from is None:                       # jeden dzień
        d = _safe_date(first.year, first.month, first.day) if first.year else \
            _nearest_future(first.month, first.day, today)
        if d is None:
            return None
        start = datetime.combine(d, first.t1 or time(0, 0))
        end = datetime.combine(d, first.t2) if first.t2 else None
        if end and end <= start:                                           # "22:00-02:00" = do rana
            end = None
        return DateSpan(start, end, has_time=first.t1 is not None)

    # zakres: "10-12.10" (jeden punkt z day_from) albo dwa punkty "A - B"
    if len(points) == 1:
        start_pt = _Point(None, first.day_from, first.month, first.year, first.t1, None)
        end_pt = _Point(None, first.day, first.month, first.year, first.t2, None)
    else:
        start_pt = first if first.day_from is None else _Point(None, first.day_from, first.month, first.year,
                                                               first.t1, None)
        end_pt = last
    end_year = end_pt.year or start_pt.year
    end_d = _safe_date(end_year, end_pt.month, end_pt.day) if end_year else \
        _nearest_future(end_pt.month, end_pt.day, today)
    if end_d is None:
        return None
    start_year = start_pt.year or (end_d.year if (start_pt.month, start_pt.day) <= (end_pt.month, end_pt.day)
                                   else end_d.year - 1)
    start_d = _safe_date(start_year, start_pt.month, start_pt.day)
    if start_d is None or start_d > end_d:
        return None
    start = datetime.combine(start_d, start_pt.t1 or time(0, 0))
    end = datetime.combine(end_d, end_pt.t1 or END_OF_DAY)
    if end <= start:
        end = datetime.combine(end_d, END_OF_DAY)
    return DateSpan(start, end, has_time=start_pt.t1 is not None)


# --------------------------------------------------------------------------- #
# Ceny
# --------------------------------------------------------------------------- #

_NUM = r"\d{1,3}(?:[  ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_PRICE_GROUP_RE = re.compile(rf"((?:(?:{_NUM})\s*(?:-|/|,|i|lub|albo)\s*)*(?:{_NUM}))\s*(?:zl|pln)\b")
_FREE_RE = re.compile(
    r"wstep\W{0,3}(?:jest\s+)?(?:wolny|bezplatny|darmowy)|wejscie\W{0,3}(?:wolne|bezplatne)"
    r"|bezplatn|darmow|za darmo|nieodplatn|free entry|admission free"
)
# zdanie opisu musi mówić o biletach/wstępie ("wynagrodzenie od 3000 zł" na targach pracy to nie cena)
_PRICE_CONTEXT_RE = re.compile(r"bilet|wstep|wejsci|cen[ay] |cennik|koszt udzial|oplat[ay] (?:za )?(?:udzial|wstep)|oplat\w* startow|wpisow")
MAX_TICKET_PRICE = 2000.0


def _amounts(group: str) -> list[float]:
    return [float(n.replace(" ", "").replace(" ", "").replace(",", "."))
            for n in re.findall(_NUM, group)]


def parse_price(text: str) -> float | None:
    """Cena biletu w PLN: 'wstęp wolny' -> 0, 'od 40 zł' -> 40, '60/40 zł' -> 60, brak -> None.

    Normalna/ulgowa ('60/40 zł', '31 zł (normalny) 26 zł (ulgowy)') -> normalna; zakres lub kilka kwot
    ('40-110 zł', 'od 59 zł') -> najniższa.
    Kwota ma pierwszeństwo przed frazą o darmowym wstępie ('30 zł, dzieci wstęp wolny' -> 30).
    """
    folded = fold_text(text or "").replace("–", "-").replace("—", "-")
    found: list[tuple[float, bool]] = []
    for m in _PRICE_GROUP_RE.finditer(folded):
        values = _amounts(m.group(1))
        if "/" in m.group(1):                  # "60/40 zł" = normalny/ulgowy -> pierwsza to normalna
            found.append((values[0], True))
            continue
        tail = re.split(r"\d", folded[m.end():m.end() + 20], maxsplit=1)[0]
        normal = "normaln" in tail
        found.extend((value, normal) for value in values)
    found = [(v, is_normal) for v, is_normal in found if v <= MAX_TICKET_PRICE]   # pakiety VIP / kwoty nagród
    if found:
        normal_prices = [v for v, is_normal in found if is_normal]
        return min(normal_prices) if normal_prices else min(v for v, _ in found)
    if _FREE_RE.search(folded):
        return 0.0
    return None


def find_price(info: str, description: str = "") -> float | None:
    """Najpierw dedykowane pole z ceną, potem tylko zdania opisu mówiące o biletach/wstępie
    (żeby '10 000 zł nagrody' w opisie nie stało się ceną biletu)."""
    price = parse_price(info)
    if price is not None:
        return price
    sentences = re.split(r"(?<=[.!?])\s+|\n", description or "")
    relevant = [s for s in sentences if _PRICE_CONTEXT_RE.search(fold_text(s))]
    return parse_price(" ".join(relevant))


# --------------------------------------------------------------------------- #
# Kategorie
# --------------------------------------------------------------------------- #

# Kolejność ma znaczenie: pierwsza pasująca reguła wygrywa ("Festiwale i przeglądy filmowe" -> FESTIVAL).
_CATEGORY_RULES: list[tuple[str, Category]] = [
    (r"festiwal|festival", Category.FESTIVAL),
    (r"film|kino", Category.CINEMA),
    (r"wystaw|galeri|ekspozyc", Category.EXHIBITION),
    (r"opera\b|muzyk|muzycz|koncert", Category.MUSIC),
    (r"spektakl|teatr|przedstawien|operetk|musical|balet|dla dzieci", Category.THEATRE),
    (r"sport", Category.SPORT),
    (r"spotkani|literac|slajdowisk|meetup", Category.MEETUP),
    (r"warsztat|wyklad", Category.WORKSHOP),
    (r"spacer|zwiedzan|plener|happening", Category.OUTDOOR),
    (r"kulinar|jedzen|gastro", Category.FOOD),
]
# Typ ogólny ("Pozostałe", brak) -> kategoria z tagów wykrytych w tytule/opisie.
_CATEGORY_FROM_TAGS: list[tuple[set[str], Category]] = [
    ({"bieganie", "rower", "joga", "piłka nożna"}, Category.SPORT),
    ({"wino", "kawa", "street food", "gotowanie"}, Category.FOOD),
    ({"spacery", "natura"}, Category.OUTDOOR),
    ({"rękodzieło"}, Category.WORKSHOP),
    ({"planszówki", "języki obce", "startupy", "python", "technologia"}, Category.MEETUP),
    ({"jazz", "rock", "indie", "techno", "klasyka", "opera"}, Category.MUSIC),
    ({"kino"}, Category.CINEMA),
    ({"teatr"}, Category.THEATRE),
]


def map_category(source_type: str, title: str = "", description: str = "") -> Category:
    """Typ wydarzenia ze źródła (np. 'Spektakle teatralne') -> Category; w razie wątpliwości OTHER."""
    folded = fold_text(source_type or "")
    for pattern, category in _CATEGORY_RULES:
        if re.search(pattern, folded):
            return category
    tags = set(extract_tags(f"{title} {description}"))
    for tag_set, category in _CATEGORY_FROM_TAGS:
        if tags & tag_set:
            return category
    return Category.OTHER


# --------------------------------------------------------------------------- #
# Tagi (to na nich działa matching M4!)
# --------------------------------------------------------------------------- #

# tag -> wzorce regex na tekście po fold_text (bez ogonków, małe litery); dopasowanie od początku słowa.
# Tagi spoza INTEREST_TAGS (pop, hip-hop, folk, blues, dla dzieci) są dozwolone — trafiają do słownika filtrów.
TAG_KEYWORDS: dict[str, list[str]] = {
    "jazz": [r"jazz", r"swing", r"bebop", r"big ?band"],
    "rock": [r"rock", r"punk(?:a|u|owy|owa|owe|owej|owych|rock)?\b", r"metal(?:u|em|owy|owa|owe|owej|owych|core)?\b",
             r"hardcore", r"grunge", r"progresyw", r"stoner", r"psychodel"],
    "indie": [r"indie", r"alternatyw", r"shoegaze", r"szugejz", r"post-?punk", r"dream ?pop"],
    "techno": [r"techno", r"house\b", r"elektronik", r"elektroniczn", r"dj\b", r"drum ?(?:and|&|n) ?bass",
               r"rave\b", r"klubow[aey]\b"],
    "klasyka": [r"symfoni", r"filharmon", r"kwartet", r"orkiestr", r"recital", r"kameraln", r"klasyczn",
                r"organow", r"organy\b", r"chopin", r"bach\b", r"mozart", r"beethoven", r"fortepian", r"wiolonczel",
                r"skrzyp", r"kantat", r"oratori", r"barok", r"szymanowsk", r"dvorak", r"czajkowsk", r"pianist"],
    "opera": [r"oper(?:a|y|ze|e|owa|owy|owe|owej|owych)\b", r"opera rara"],
    "teatr": [r"teatr", r"spektakl", r"przedstawien", r"monodram", r"inscenizac"],
    "kino": [r"film", r"kino\b", r"kina\b", r"kinie\b", r"kinow", r"seans", r"przedpremier", r"dokumentaln",
             r"animac"],
    "stand-up": [r"stand-? ?up", r"kabaret", r"open mic", r"komik"],
    "sztuka współczesna": [r"sztuk[aiey] wspolczesn", r"sztuk[aiy]? wizualn", r"galeri", r"instalacj", r"malarstw",
                           r"malarz", r"rzezb", r"wernisaz", r"performans", r"wideoart", r"mocak", r"bunkier sztuki",
                           r"cricotek", r"abstrakc"],
    "fotografia": [r"fotogra", r"zdjec", r"photo", r"foto\b", r"fotospacer"],
    "design": [r"design", r"projektow", r"plakat", r"typografi", r"grafik", r"graficzn", r"ilustrac", r"fashion",
               r"moda\b", r"mody\b"],
    "architektura": [r"architekt", r"modernizm", r"urbanist", r"brutalizm"],
    # "historia/historie" w opisach to zwykle "opowieść" -> tylko jednoznaczne formy
    "historia": [r"historyczn", r"histori[aeiy] (?:polski|krakowa|miasta|sztuki|zydow|europy|xx)", r"dziejow",
                 r"muzeum", r"muzealn", r"zabyt", r"twierdz", r"wojn", r"dziedzictw", r"archeolog", r"legend(?!arn)",
                 r"sredniowiecz", r"okupacj", r"rekonstrukc", r"powstani", r"wawel"],
    "literatura": [r"literat", r"literack", r"ksiazk", r"ksiazek", r"poezj", r"poet", r"pisarz", r"pisark",
                   r"(?:spotkani\w*|wieczor\w*) autorsk", r"czytan", r"reportaz", r"kryminal", r"wiersz", r"wydawc", r"powiesc", r"proza\b"],
    # "maraton" sam w sobie bywa filmowy/programistyczny -> tylko półmaraton albo maraton w kontekście biegu
    "bieganie": [r"bieg(?:i|u|iem|owy|owe|acz\w*)?\b", r"polmaraton", r"maraton\w* (?:biegow|uliczn|krakow)",
                 r"cracovia maraton", r"run\b", r"running", r"piatka\b"],
    "rower": [r"rower", r"kolarsk", r"bike", r"cycling"],
    "joga": [r"joga", r"jogi\b", r"yoga", r"medytac", r"pilates"],
    "piłka nożna": [r"pilk[aiey] nozn", r"pilkarsk", r"ekstraklas", r"futbol", r"football"],
    "natura": [r"przyrod", r"natur(?:a|y|ze|e)\b", r"ogrod", r"botaniczn", r"ekolog", r"zwierz", r"ptak", r"lesn", r"las\b"],
    "spacery": [r"spacer", r"zwiedzan", r"przewodnik", r"wycieczk", r"oprowadzan", r"szlak"],
    "planszówki": [r"planszow", r"plansz[ayei]\b", r"board ?game"],
    "gry wideo": [r"gry wideo", r"gier wideo", r"gier komputerow", r"gaming", r"gamer", r"e-?sport",
                  r"video ?game", r"muzyk[aiey] z gier", r"wiedzmin", r"nier:", r"clair obscur"],
    "technologia": [r"technolog", r"robot", r"ai\b", r"sztuczn\w* inteligenc", r"programow", r"hackathon",
                    r"hackyeah", r"cyfrow", r"wirtualn", r"kodowan", r"druk 3d", r"nowe media"],
    "python": [r"python"],
    "startupy": [r"startup", r"start-up", r"przedsiebiorcz", r"pitch\b", r"inwestor"],
    "nauka": [r"nauk", r"wyklad", r"fizyk", r"chemi", r"astronom", r"eksperyment", r"kosmos", r"biolog",
              r"matematy", r"science"],
    "języki obce": [r"jezyk\w* obc", r"language", r"in english", r"po angielsku", r"konwersac"],
    "gotowanie": [r"gotowan", r"kulinar", r"kuchni", r"szef kuchni", r"pieczen"],
    "street food": [r"street ?food", r"food ?truck", r"jarmark", r"festiwal smak", r"targ sniadaniow"],
    "kawa": [r"kaw(?:a|y|e|ie|ka|iarnia|iarni)\b", r"cafe\b", r"espresso", r"barista"],
    "wino": [r"win(?:o|a|em|ie)\b", r"winiar", r"winnic", r"degustac", r"sommelier", r"enolog"],
    "taniec": [r"tanc", r"taniec", r"taneczn", r"balet", r"flamenco", r"tango", r"salsa", r"dance", r"choreograf",
               r"potancowk"],
    "rękodzieło": [r"rekodziel", r"ceramik", r"haft", r"szydel", r"handmade", r"rzemiosl", r"linoryt",
                   r"makram", r"warsztaty plastyczn"],
    # poza kanonicznym słownikiem — ale przydatne w filtrach i w profilach "własnych tagów"
    "pop": [r"pop(?:u|em|owy|owa|owe|owej|owych)?\b", r"przeboj", r"hity\b"],
    "hip-hop": [r"hip-? ?hop", r"rap(?:u|em|owy|owa|owe|owej)?\b", r"raper"],
    "folk": [r"folk", r"(?:muzyk|piesn|zespol|kapel|tanc)\w* ludow", r"etno\b", r"etniczn", r"fado"],  # nie "Teatr Ludowy"
    "blues": [r"blues"],
    "dla dzieci": [r"dla dzieci", r"dzieci\b", r"rodzinn", r"familijn", r"\d{1,2}\+"],
}
_TAG_RES = {
    tag: re.compile(r"(?<![a-z0-9])(?:" + "|".join(patterns) + ")") for tag, patterns in TAG_KEYWORDS.items()
}
# typ wydarzenia ze źródła -> tagi domyślne (zawsze dopisywane)
_TYPE_TAGS: list[tuple[str, list[str]]] = [
    (r"spektakl|teatr|przedstawien|operetk|musical", ["teatr"]),
    (r"taneczn|balet", ["taniec"]),
    (r"kabaret|stand", ["stand-up"]),
    (r"film|kino", ["kino"]),
    (r"klasyczn|filharmon", ["klasyka"]),
    (r"opera\b", ["opera"]),
    (r"klubow", ["techno"]),
    (r"literac|literatur", ["literatura"]),
    (r"spacer|zwiedzan", ["spacery"]),
    (r"dzieci|dziecie", ["dla dzieci"]),
]
_ART_TAGS = {"sztuka współczesna", "fotografia", "historia", "design", "architektura"}


def extract_tags(text: str, source_type: str = "") -> list[str]:
    """Słowa kluczowe w tytule/opisie + typ ze źródła -> tagi (znormalizowane, bez duplikatów)."""
    folded = fold_text(f"{source_type} {text}")
    tags = [tag for tag, regex in _TAG_RES.items() if regex.search(folded)]
    folded_type = fold_text(source_type or "")
    for pattern, defaults in _TYPE_TAGS:
        if re.search(pattern, folded_type):
            tags.extend(defaults)
    if re.search(r"wystaw|sztuk wizualn", folded_type) and not _ART_TAGS.intersection(tags):
        tags.append("sztuka współczesna")
    seen: dict[str, None] = {}
    for tag in tags:
        seen.setdefault(normalize_tag(tag), None)
    return list(seen)
