"""
M3 — persony demo (czysta logika, BEZ streamlit).

Przełącznik „Zaloguj jako” pokazuje przy osobach z mocków krótki znacznik roli, a pod listą
scenariusz wybranej persony; kolejność idzie za scenariuszem demo (ARCHITECTURE.md §11), więc
prowadzący przełącza persony bez zastanowienia. ID mocków są stałe (shared/mock_data.py);
nowe profile z onboardingu pokazują samo imię.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import NamedTuple

from shared.models import User


class Persona(NamedTuple):
    tag: str        # krótko — lista w ⚙️ Opcje jest wąska (ok. 360 px)
    scenario: str   # pełniejszy opis pod listą (zawija się)


# Kolejność = kolejność w przełączniku.
DEMO_PERSONAS: dict[str, Persona] = {
    "u_ola": Persona("🎬 start demo", "Nowa w Krakowie, lubi jazz. Filtry: Dziś + Muzyka → jam session."),
    "u_kuba": Persona("💬 czat", "Druga karta (?user=u_kuba): odpisuje Oli w czacie wydarzenia."),
    "u_bartek": Persona("🤝 top Oli", "Top dopasowanie Oli: jazz i fotografia, wiele wspólnych wydarzeń."),
    "u_natalia": Persona("🤝 wystawy", "Wystawy i teatr — drugie dopasowanie Oli na jam session."),
    "u_tomek": Persona("stand-up", "Stand-up i kino; idzie na jam session, mało wspólnego z Olą."),
    "u_marta": Persona("🙈 prywatność", "Ukryta w dopasowaniach na pokazie w Kinie Kijów."),
    "u_lukas": Persona("Erasmus", "Erasmus z Lipska: wymiana językowa, techno, historia."),
    "u_ania": Persona("opera", "Przewodniczka po Krakowie: opera, historia, architektura."),
    "u_piotr": Persona("meetupy", "Rano biega, wieczorem meetupy Python."),
    "u_michal": Persona("startupy", "Founder: startupy, planszówki, gry wideo."),
    "u_zosia": Persona("techno", "Fotografka i tancerka, noc należy do techno."),
    "u_julia": Persona("joga", "Joga o świcie, natura, języki obce."),
}


def persona_label(user: User) -> str:
    """'Ola · 🎬 start demo' dla persony demo, samo imię dla pozostałych."""
    persona = DEMO_PERSONAS.get(user.id)
    return f"{user.name} · {persona.tag}" if persona else user.name


def switcher_labels(users: Iterable[User]) -> dict[str, str]:
    """{id: etykieta} do „Zaloguj jako” — zawsze unikalne.

    Selectbox Streamlita odnajduje wybór po TEKŚCIE etykiety, więc dwie osoby o tym samym imieniu
    (np. „Ewa” z onboardingu i „Ewa” z danych przykładowych) przełączałyby na złą osobę.
    Powtórzone etykiety dostają końcówkę ID: „Ewa · #a1b2”.
    """
    users = list(users)
    labels = {u.id: persona_label(u) for u in users}
    counts = Counter(labels.values())
    return {uid: f"{label} · #{uid[-4:]}" if counts[label] > 1 else label for uid, label in labels.items()}


def persona_scenario(user_id: str) -> str | None:
    persona = DEMO_PERSONAS.get(user_id)
    return persona.scenario if persona else None


def sort_for_switcher(users: Iterable[User]) -> list[User]:
    """Persony w kolejności scenariusza, potem pozostali (np. z onboardingu) alfabetycznie."""
    order = {uid: i for i, uid in enumerate(DEMO_PERSONAS)}
    return sorted(users, key=lambda u: (order.get(u.id, len(order)), u.name.lower(), u.id))
