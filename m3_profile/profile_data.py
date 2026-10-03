"""
M3 — dane do podglądu profilu (czysta logika, BEZ streamlit -> testowalna pytestem).

    overlap = profile_overlap(storage, viewer=zalogowany, profile=oglądany)

Co oglądający ma wspólnego z osobą: zainteresowania (wspólne najpierw) i PRZYSZŁE wydarzenia
(wspólne / pozostałe). Prywatność: na cudzym profilu nie pokazujemy wydarzeń, przy których
osoba wyłączyła „Pokaż mnie innym w dopasowaniach” (Attendance.open_to_meet=False).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from shared.models import Event, User, now
from shared.storage import Storage


@dataclass(frozen=True)
class ProfileOverlap:
    shared_tags: list[str] = field(default_factory=list)     # w kolejności z profilu oglądanej osoby
    other_tags: list[str] = field(default_factory=list)
    common_events: list[Event] = field(default_factory=list)  # obie osoby się wybierają (rosnąco po dacie)
    other_events: list[Event] = field(default_factory=list)   # tylko oglądana osoba
    hidden_event_ids: frozenset[str] = frozenset()            # własny profil: ukryte w dopasowaniach


def is_upcoming(event: Event, at: datetime) -> bool:
    """Przyszłe albo trwające (wystawa do końca miesiąca też się liczy)."""
    return event.end_or_start >= at


def profile_overlap(
    storage: Storage, viewer: User | None, profile: User, *, at: datetime | None = None
) -> ProfileOverlap:
    at = at or now()
    own = viewer is not None and viewer.id == profile.id
    viewer_tags = set(viewer.tags) if viewer and not own else set()
    shared_tags = [t for t in profile.tags if t in viewer_tags]
    other_tags = [t for t in profile.tags if t not in viewer_tags]

    attendance = [a for a in storage.list_user_attendance(profile.id) if own or a.open_to_meet]
    viewer_event_ids = (
        {a.event_id for a in storage.list_user_attendance(viewer.id)} if viewer and not own else set()
    )
    events = sorted(
        (e for a in attendance if (e := storage.get_event(a.event_id)) and is_upcoming(e, at)),
        key=lambda e: (e.start, e.id),
    )
    return ProfileOverlap(
        shared_tags=shared_tags,
        other_tags=other_tags,
        common_events=[e for e in events if e.id in viewer_event_ids],
        other_events=[e for e in events if e.id not in viewer_event_ids],
        hidden_event_ids=frozenset(a.event_id for a in attendance if own and not a.open_to_meet),
    )
