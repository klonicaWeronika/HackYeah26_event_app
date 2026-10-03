"""
M3-08 — prywatność w dopasowaniach (czysta logika, BEZ streamlit).

Wariant „tylko M3” (decyzja zespołu): widoczność dalej żyje w zapisach na wydarzenia
(`Attendance.open_to_meet`, przełącznik M5 przy wydarzeniu, filtr w M4 `match_for_event`).
Tu tylko ZBIORCZO ustawiamy ją we wszystkich zapisach osoby.

Ograniczenia (świadome): nowe „Idę!” w M5 zapisuje domyślne open_to_meet=True, a „pokaż wszędzie”
nie przywraca wcześniejszych ustawień poszczególnych wydarzeń.
"""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from m3_profile.profile_data import is_upcoming
from shared.models import now
from shared.storage import Storage


class Visibility(NamedTuple):
    visible: int      # nadchodzące wydarzenia, na których osoba jest widoczna w dopasowaniach
    total: int        # wszystkie nadchodzące wydarzenia osoby

    @property
    def hidden(self) -> int:
        return self.total - self.visible


def visibility_summary(storage: Storage, user_id: str, *, at: datetime | None = None) -> Visibility:
    at = at or now()
    upcoming = [
        a for a in storage.list_user_attendance(user_id)
        if (e := storage.get_event(a.event_id)) and is_upcoming(e, at)
    ]
    return Visibility(visible=sum(a.open_to_meet for a in upcoming), total=len(upcoming))


def set_visibility_everywhere(storage: Storage, user_id: str, visible: bool) -> int:
    """Ustawia open_to_meet we WSZYSTKICH zapisach osoby (status i data zapisu bez zmian).

    Zwraca liczbę zmienionych zapisów.
    """
    changed = 0
    for att in storage.list_user_attendance(user_id):
        if att.open_to_meet != visible:
            storage.join_event(user_id, att.event_id, status=att.status, open_to_meet=visible)
            changed += 1
    return changed
