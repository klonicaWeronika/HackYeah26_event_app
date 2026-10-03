"""M2 — raport jakości danych drukowany po każdym uruchomieniu pipeline'u (czysta funkcja: eventy -> tekst)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from shared.models import INTEREST_TAGS, Event

_CANONICAL = set(INTEREST_TAGS)


def _pct(part: int, total: int) -> str:
    return f"{part} ({100 * part / total:.0f}%)" if total else "0"


def quality_report(events: Iterable[Event], dropped: dict[str, Counter] | None = None) -> str:
    """Raport per źródło + łącznie. `dropped` = {źródło: Counter(powód -> liczba)} z etapu zbierania."""
    events = list(events)
    dropped = dropped or {}
    by_source: dict[str, list[Event]] = {}
    for e in events:
        by_source.setdefault(e.source, []).append(e)

    lines = ["", "=== Raport jakości danych M2 ==="]
    rows = [(name, evs) for name, evs in sorted(by_source.items())] + [("RAZEM", events)]
    for name, evs in rows:
        n = len(evs)
        drop = dropped.get(name.removeprefix("scraper:"), Counter()) if name != "RAZEM" else \
            sum(dropped.values(), Counter())
        lines.append(
            f"{name:16} {n:4} eventów | bez ceny: {_pct(sum(e.price_pln is None for e in evs), n)}"
            f" | darmowe: {sum(e.price_pln == 0 for e in evs)}"
            f" | bez opisu: {_pct(sum(not e.description for e in evs), n)}"
            f" | bez tagów: {_pct(sum(not e.tags for e in evs), n)}"
            f" | bez tagu z INTEREST_TAGS: {_pct(sum(not _CANONICAL.intersection(e.tags) for e in evs), n)}"
            + (f" | odrzucone: {', '.join(f'{k} {v}' for k, v in drop.items())}" if drop else "")
        )
    if events:
        categories = Counter(e.category.value for e in events)
        tags = Counter(t for e in events for t in e.tags)
        lines.append(f"kategorie ({len(categories)}): " + ", ".join(f"{k} {v}" for k, v in categories.most_common()))
        lines.append("top tagi: " + ", ".join(f"{k} {v}" for k, v in tags.most_common(12)))
        lines.append(f"zakres dat: {min(e.start for e in events):%Y-%m-%d} … {max(e.start for e in events):%Y-%m-%d}")
    return "\n".join(lines)
