"""
M2 — normalizacja surowych pól ze źródeł: polskie daty -> datetime.

Czyste funkcje (tekst -> dane), bez sieci i bez stanu — testowane tabelarycznie w tests/.
Wszystkie datetime są NAIWNE (czas lokalny Europe/Warsaw), zgodnie z shared/models.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time

from shared.models import fold_text

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
        return None

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
