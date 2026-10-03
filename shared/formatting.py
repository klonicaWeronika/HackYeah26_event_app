"""shared/formatting.py — wspólne formatowanie dat/cen po polsku (UI wszystkich modułów)."""

from __future__ import annotations

from datetime import date, datetime

from shared.models import Event

_PL_DAYS = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]


def format_day(d: date, today: date | None = None) -> str:
    today = today or date.today()
    delta = (d - today).days
    if delta == 0:
        return "dziś"
    if delta == 1:
        return "jutro"
    return f"{_PL_DAYS[d.weekday()]} {d.day}.{d.month:02d}"


def format_when(event: Event, today: date | None = None) -> str:
    """'dziś · 20:00–23:00', 'sob 11.10 · 19:00', 'do 2.11' (dla eventów trwających wiele dni)."""
    start, end = event.start, event.end
    if end and (end.date() - start.date()).days >= 1:
        return f"{format_day(start.date(), today)} – {end.day}.{end.month:02d}"
    span = f"{start:%H:%M}" + (f"–{end:%H:%M}" if end else "")
    return f"{format_day(start.date(), today)} · {span}"


def format_price(price_pln: float | None) -> str:
    if price_pln is None:
        return "cena nieznana"
    if price_pln == 0:
        return "wstęp wolny"
    return f"{price_pln:.0f} zł"


def format_time(dt: datetime) -> str:
    return f"{dt:%H:%M}" if dt.date() == date.today() else f"{dt.day}.{dt.month:02d} {dt:%H:%M}"
