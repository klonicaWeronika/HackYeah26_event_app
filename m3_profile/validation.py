"""
M3 — walidacja i normalizacja profilu (czysta logika, BEZ streamlit -> testowalna pytestem).

    clean, errors = validate_profile(name, bio, tags)
    if not errors:
        storage.upsert_user(user.copy_with(**clean))

`clean` zawsze zawiera znormalizowane wartości (także gdy są błędy), a `errors` to
{pole: komunikat PL} dla pól "name" / "bio" / "tags" — UI pokazuje je pod polami.
Używane przez edycję profilu (M3-03) i onboarding (M3-04).
"""

from __future__ import annotations

from collections.abc import Iterable

from shared.models import normalize_tag

NAME_MAX = 60          # = User.name max_length
BIO_MAX = 280
TAGS_MIN = 3
TAGS_MAX = 10
TAG_MAX_LEN = 30       # własne tagi dopisywane w multiselect


def normalize_name(name: str) -> str:
    """'  Ola   Kowalska ' -> 'Ola Kowalska' (bez wiodących/zdublowanych spacji)."""
    return " ".join((name or "").split())


def normalize_bio(bio: str) -> str:
    """Ujednolica końce linii, obcina spacje na końcach linii i maks. 1 pusta linia z rzędu."""
    lines = [line.rstrip() for line in (bio or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def normalize_tags(tags: Iterable[str] | None) -> list[str]:
    """['#Jazz', ' jazz ', 'Kino'] -> ['jazz', 'kino'] — ta sama normalizacja co w modelu User."""
    seen: dict[str, None] = {}
    for raw in tags or []:
        tag = normalize_tag(str(raw))
        if tag:
            seen.setdefault(tag, None)
    return list(seen)


def validate_profile(name: str, bio: str, tags: Iterable[str] | None) -> tuple[dict, dict[str, str]]:
    """Zwraca (clean, errors): clean = {"name", "bio", "tags"} gotowe do `user.copy_with(**clean)`."""
    clean = {"name": normalize_name(name), "bio": normalize_bio(bio), "tags": normalize_tags(tags)}
    errors: dict[str, str] = {}

    if not clean["name"]:
        errors["name"] = "Podaj imię albo nick."
    elif len(clean["name"]) > NAME_MAX:
        errors["name"] = f"Imię może mieć maks. {NAME_MAX} znaków (teraz {len(clean['name'])})."

    if len(clean["bio"]) > BIO_MAX:
        errors["bio"] = f"Opis może mieć maks. {BIO_MAX} znaków (teraz {len(clean['bio'])})."

    too_long = [t for t in clean["tags"] if len(t) > TAG_MAX_LEN]
    count = len(clean["tags"])
    if too_long:
        shown = too_long[0] if len(too_long[0]) <= 40 else too_long[0][:39] + "…"
        errors["tags"] = f"Zainteresowanie „{shown}” jest za długie (maks. {TAG_MAX_LEN} znaków)."
    elif count < TAGS_MIN:
        missing = TAGS_MIN - count
        errors["tags"] = (
            f"Wybierz co najmniej {TAGS_MIN} zainteresowania (brakuje {missing}) — "
            "dzięki nim znajdziemy osoby podobne do Ciebie."
        )
    elif count > TAGS_MAX:
        errors["tags"] = f"Wybierz maks. {TAGS_MAX} zainteresowań (teraz {count}) — usuń {count - TAGS_MAX}."

    return clean, errors
