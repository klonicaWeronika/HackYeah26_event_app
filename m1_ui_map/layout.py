"""
M1 — layout aplikacji: mapa na cały ekran i pływające nad nią elementy.

    ┌────────────── górny pasek: logo │ [🔍 szukaj │ 📍 lokalizacja + promień │ ●] │ dodaj · osoba · menu ┐
    │                         pasek kategorii: kółka z ikonami i liczbą wydarzeń                          │
    ├──────────────┐                                                                    ┌────────────────┤
    │ lista        │◀                    MAPA (cały ekran, pod spodem)                 ▶│ szczegóły /    │
    │ wydarzeń     │                                                                    │ polecane       │
    │ + filtry     │                                                                    │                │
    └──────────────┘                         [ − + ⌖ ]                                  └────────────────┘

Panele chowają się uchwytem na krawędzi (◀ ▶). Czat / profil / formularz otwierają się jako szeroki
arkusz w miejscu listy — mapa pod spodem zostaje zamontowana (bez resetu widoku).
Styl: ikony Material zamiast emoji, kolory w zmiennych CSS -> jasny i ciemny motyw (patrz styles.py).
"""

from __future__ import annotations

import base64
import html
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from m1_ui_map.location import (
    DEFAULT_RADIUS_KM, PICKED_PLACE, PLACES, RADIUS_STEPS_KM, Place, event_distance_km, format_distance,
    format_radius, within_radius, zoom_for_radius,
)
from m1_ui_map.map_view import CATEGORY_COLORS, MapFocus, pin_positions
from m1_ui_map.styles import category_css, global_css, state_css
from m3_profile.views import avatar_html, render_user_card, render_user_switcher
from m4_matching.engine import match_for_event, plural_pl
from m4_matching.widgets import render_recommendations
from m5_chat.chat_view import render_attendance_controls
from m5_chat.group_view import render_event_chat_entry
from m5_chat.inbox import render_inbox
from shared import state
from shared.config import APP_NAME, APP_TAGLINE, FEATURES, MAX_MATCHES_IN_PANEL
from shared.formatting import format_price, format_when
from shared.models import CATEGORY_META, Category, Event, FilterCriteria, User
from shared.state import View
from shared.storage import Storage

_ASSETS = Path(__file__).resolve().parent / "assets"
LOGO_PATH = str(_ASSETS / "logo.svg")             # znak + „KRK Razem”
LOGO_MARK_PATH = str(_ASSETS / "logo_mark.svg")   # sam znak (górny pasek, favicon)

PAGE_SIZE = 25                                    # kart na liście, potem „Pokaż więcej”
WHOLE_CITY = "Cały Kraków"
_MENU_KEY = "m1_menu"                             # stan popovera „Menu” (True = otwarte)
_LOC_KEY = "m1_loc"                               # stan popovera lokalizacji
_FILTER_FIELDS = ("query", "cats", "when", "dates", "tags", "free", "sort", "place", "radius")

_CATEGORY_ICONS: dict[Category, str] = {
    Category.MUSIC: "music_note",
    Category.THEATRE: "theater_comedy",
    Category.CINEMA: "movie",
    Category.EXHIBITION: "palette",
    Category.FESTIVAL: "celebration",
    Category.SPORT: "directions_run",
    Category.MEETUP: "groups",
    Category.WORKSHOP: "construction",
    Category.FOOD: "restaurant",
    Category.OUTDOOR: "park",
    Category.OTHER: "more_horiz",
}

DATE_PRESETS: dict[str, str] = {
    "today": "Dziś", "tomorrow": "Jutro", "weekend": "Weekend", "7d": "7 dni", "14d": "14 dni",
    "any": "Zawsze", "custom": ":material/edit_calendar: Daty",
}
DEFAULT_PRESET = "14d"
SORTS: dict[str, str] = {
    "soon": "Najbliższy termin", "popular": "Najpopularniejsze", "near": "Najbliżej", "cheap": "Najtańsze",
}


def inject_css(dark: bool = False) -> None:
    st.markdown(global_css(dark), unsafe_allow_html=True)


def is_dark_theme() -> bool:
    try:
        return st.context.theme.type == "dark"
    except AttributeError:            # starsze Streamlity / AppTest bez motywu
        return False


def category_label(category: Category) -> str:
    """Etykieta kategorii: ikona Material + nazwa PL (bez emoji)."""
    return f":material/{_CATEGORY_ICONS[category]}: {CATEGORY_META[category].label}"


def plans_caption(going: int) -> str:
    """Podpis pod imieniem w górnym pasku: '1 wydarzenie w planach', '14 wydarzeń w planach'."""
    if going == 0:
        return "Brak planów — wybierz coś na mapie"
    return f"{going} {plural_pl(going, 'wydarzenie', 'wydarzenia', 'wydarzeń')} w planach"


def date_range_for(preset: str | None, today: date, custom: object = None) -> tuple[date | None, date | None]:
    """Zakres dat dla presetu. „Weekend” = najbliższa sobota–niedziela (w niedzielę: tylko dziś)."""
    if preset == "today":
        return today, today
    if preset == "tomorrow":
        return today + timedelta(days=1), today + timedelta(days=1)
    if preset == "weekend":
        if today.weekday() == 6:
            return today, today
        saturday = today + timedelta(days=(5 - today.weekday()) % 7)
        return saturday, saturday + timedelta(days=1)
    if preset == "7d":
        return today, today + timedelta(days=7)
    if preset == "14d":
        return today, today + timedelta(days=14)
    if preset == "custom":
        picked = list(custom) if isinstance(custom, (list, tuple)) else [custom] if custom else []
        if picked:
            return picked[0], picked[1] if len(picked) > 1 else picked[0]
        return today, today + timedelta(days=14)
    return today, None                                  # „Kiedykolwiek” albo odznaczony preset


_PL_WEEKDAYS = ("poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela")
_PL_MONTHS = ("stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
              "października", "listopada", "grudnia")


def full_date(event: Event) -> str:
    """'sobota, 19 września 2026' albo '19 września – 4 października 2026' (wydarzenia wielodniowe)."""
    start, end = event.start.date(), event.end_or_start.date()
    if end > start:
        first = f"{start.day} {_PL_MONTHS[start.month - 1]}"
        if start.year != end.year:
            first += f" {start.year}"
        return f"{first} – {end.day} {_PL_MONTHS[end.month - 1]} {end.year}"
    return f"{_PL_WEEKDAYS[start.weekday()]}, {start.day} {_PL_MONTHS[start.month - 1]} {start.year}"


def _icon(name: str) -> str:
    return f'<span class="material-ico">{name}</span>'


def _css_url(url: str | None) -> str | None:
    """URL obrazka bezpieczny do `background-image: url("...")` w atrybucie style."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    for char, code in (('"', "%22"), ("'", "%27"), ("(", "%28"), (")", "%29"), ("\\", "%5C"), ("<", "%3C"),
                       (">", "%3E"), (" ", "%20")):
        url = url.replace(char, code)
    return url


# --------------------------------------------------------------------------- #
# Stan filtrów (klucze widgetów z numerem wersji — „Wyczyść” podbija wersję)
# --------------------------------------------------------------------------- #

def _filter_key(field: str) -> str:
    """Klucz widgetu filtra z numerem wersji: „Wyczyść” podbija wersję -> widgety montują się od nowa
    z wartościami domyślnymi (samo usunięcie kluczy zostawiało w przeglądarce stare wartości)."""
    return f"m1_f_{field}_{st.session_state.get('m1_f_ver', 0)}"


def _clear_filters() -> None:
    for field in _FILTER_FIELDS:
        st.session_state.pop(_filter_key(field), None)
    st.session_state["m1_f_ver"] = st.session_state.get("m1_f_ver", 0) + 1
    st.session_state["m1_page"] = PAGE_SIZE


def current_location() -> tuple[str, Place | None, float | None]:
    """(nazwa miejsca, środek, promień km) — środek None = cały Kraków (bez promienia)."""
    name = st.session_state.get(_filter_key("place")) or WHOLE_CITY
    radius = st.session_state.get(_filter_key("radius"), DEFAULT_RADIUS_KM)
    if name == PICKED_PLACE and (picked := st.session_state.get("m1_picked")):
        return name, Place(*picked), radius
    if name in PLACES:
        return name, PLACES[name], radius
    return WHOLE_CITY, None, None


# --------------------------------------------------------------------------- #
# Górny pasek: logo, wyszukiwarka z lokalizacją, akcje + menu
# --------------------------------------------------------------------------- #

@st.cache_data
def _logo_mark_uri() -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(Path(LOGO_MARK_PATH).read_bytes()).decode()


def _brand_html() -> str:
    first, _, rest = APP_NAME.partition(" ")
    return (
        f'<div class="m1-brand"><img src="{_logo_mark_uri()}" alt="">'
        f'<div><div class="m1-brand-name">{html.escape(first)}<span>{html.escape(rest)}</span></div>'
        f'<div class="m1-brand-tag">{html.escape(APP_TAGLINE)}</div></div></div>'
    )


def _user_html(user: User, avatar_size: int, subtitle: str) -> str:
    return (
        f'<div class="m1-header">{avatar_html(user, avatar_size)}'
        f'<div><div class="m1-hello">{html.escape(user.name)}</div>'
        f'<div class="m1-plans">{html.escape(subtitle)}</div></div></div>'
    )


def _close_menu() -> None:
    st.session_state[_MENU_KEY] = False


def _menu_go_to(view: View) -> None:
    _close_menu()
    state.go_to(view)


def _reset_demo(storage: Storage) -> None:
    """Callback: zapis przed przebiegiem skryptu -> cała strona widzi świeże dane w jednym rerunie."""
    storage.reset()
    state.select_event(None)
    _close_menu()
    st.toast("Przywrócono dane demo", icon=":material/restart_alt:")


def _sync_menu(user_id: str) -> None:
    """Zamyka menu, gdy akcja innego modułu zmieniła osobę albo widok (np. „Zaloguj jako” z M3)."""
    context = (user_id, state.current_view())
    if st.session_state.get("m1_menu_ctx") != context:
        st.session_state["m1_menu_ctx"] = context
        _close_menu()


def _menu_item(label: str, icon: str, key: str, on_click, args: tuple) -> None:
    st.button(label, key=key, icon=f":material/{icon}:", type="tertiary", width="stretch",
              on_click=on_click, args=args)


def _menu_separator() -> None:
    st.markdown('<div class="m1-sep"></div>', unsafe_allow_html=True)


def _render_menu(storage: Storage, user: User) -> None:
    _sync_menu(user.id)
    with st.popover("Menu", icon=":material/menu:", key=_MENU_KEY, on_change="rerun"):
        with st.container(key="m1_menu_body", gap=None):
            st.markdown(
                f'<div class="m1-menu-user">{avatar_html(user, 32)}'
                f'<div class="m1-hello">{html.escape(user.name)}</div></div>',
                unsafe_allow_html=True,
            )
            _menu_item("Edytuj profil", "manage_accounts", "m1_menu_profile",
                       _menu_go_to, (View.PROFILE_EDIT,))
            if FEATURES["add_event"]:
                _menu_item("Dodaj wydarzenie", "add_location_alt", "m1_menu_add_event",
                           _menu_go_to, (View.ADD_EVENT,))
            _menu_separator()
            render_user_switcher(storage)                 # M3: „Zaloguj jako” + „Nowy profil”
            _menu_separator()
            with st.container(key="m1_menu_reset"):
                _menu_item("Przywróć dane demo", "restart_alt", "m1_menu_reset_btn", _reset_demo, (storage,))


def _start_pick() -> None:
    st.session_state["m1_pick"] = True
    st.session_state[_LOC_KEY] = False


def _cancel_pick() -> None:
    st.session_state["m1_pick"] = False


def apply_picked_point(lat: float, lon: float) -> None:
    """Klik na mapie w trybie wskazywania: nowy środek promienia (widget ustawi się w następnym przebiegu)."""
    st.session_state["m1_picked"] = (round(lat, 5), round(lon, 5))
    st.session_state["m1_pending_place"] = PICKED_PLACE
    st.session_state["m1_pick"] = False


def _render_location_popover() -> None:
    place_key, radius_key = _filter_key("place"), _filter_key("radius")
    # Wartości startowe przez Session State (nie `default=`): środek promienia ustawia też klik na mapie.
    st.session_state.setdefault(place_key, WHOLE_CITY)
    st.session_state.setdefault(radius_key, DEFAULT_RADIUS_KM)
    if pending := st.session_state.pop("m1_pending_place", None):
        st.session_state[place_key] = pending              # przed utworzeniem widgetu — dozwolone
    name, center, radius = current_location()
    label = f"{name} · {format_radius(radius)}" if center else WHOLE_CITY

    with st.popover(label, icon=":material/location_on:", key=_LOC_KEY, on_change="rerun"):
        with st.container(key="m1_loc_body"):
            options = [WHOLE_CITY, *PLACES] + ([PICKED_PLACE] if st.session_state.get("m1_picked") else [])
            st.pills("Okolica", options, key=place_key)
            st.select_slider("Promień", RADIUS_STEPS_KM, key=radius_key, format_func=format_radius,
                             disabled=center is None)
            st.button("Wskaż punkt na mapie", key="m1_loc_pick", icon=":material/ads_click:",
                      width="stretch", on_click=_start_pick)
            st.markdown(
                '<div class="m1-loc-hint">Wybierz okolicę albo kliknij dowolne miejsce na mapie — pokażemy '
                "tylko wydarzenia w zasięgu, a okrąg zaznaczy obszar.</div>",
                unsafe_allow_html=True,
            )


def render_header(storage: Storage, user: User) -> None:
    """Górny pasek (logo, wyszukiwarka z lokalizacją, akcje, menu) — przyklejony do góry ekranu."""
    going = len(storage.list_user_attendance(user.id))
    with st.container(key="m1_topbar_row", horizontal=True, vertical_alignment="center"):
        st.markdown(_brand_html(), unsafe_allow_html=True)
        with st.container(key="m1_search", horizontal=True, vertical_alignment="center"):
            st.text_input(
                "Szukaj", key=_filter_key("query"), placeholder="Szukaj: wydarzenie, miejsce, tag",
                icon=":material/search:", label_visibility="collapsed",
            )
            _render_location_popover()
            st.button("", key="m1_search_go", icon=":material/search:", help="Szukaj")
        with st.container(key="m1_actions", horizontal=True, vertical_alignment="center", width="content"):
            if FEATURES["add_event"]:
                st.button("Dodaj wydarzenie", key="m1_add_event_top", icon=":material/add_location_alt:",
                          on_click=state.go_to, args=(View.ADD_EVENT,))
            render_inbox(storage, user)                   # M5: grupy, zaproszenia, głosowania, DM
            st.markdown(_user_html(user, 38, plans_caption(going)), unsafe_allow_html=True)
            _render_menu(storage, user)


def render_category_bar() -> list[Category]:
    """Kółka kategorii (multi-select). Kolory i liczniki dokłada CSS z `render_category_counts`."""
    with st.container(key="m1_catbar"):
        selected = st.pills(
            "Kategorie", list(Category), selection_mode="multi", key=_filter_key("cats"),
            format_func=category_label, label_visibility="collapsed",
        )
    return list(selected or [])


def render_category_counts(counts: dict[Category, int]) -> None:
    st.markdown(category_css(list(Category), counts), unsafe_allow_html=True)


def render_pick_banner() -> None:
    if not st.session_state.get("m1_pick"):
        return
    st.markdown(
        f'<div class="m1-pick-banner">{_icon("ads_click")} '
        "Kliknij na mapie, aby ustawić środek promienia</div>",
        unsafe_allow_html=True,
    )
    with st.container(key="m1_pick_cancel"):
        st.button("Anuluj", key="m1_pick_cancel_btn", icon=":material/close:", on_click=_cancel_pick)


# --------------------------------------------------------------------------- #
# Lewy panel — filtry listy + karty wydarzeń
# --------------------------------------------------------------------------- #

def render_filters(storage: Storage, *, query: str | None = None,
                   categories: list[Category] | None = None) -> FilterCriteria:
    """Filtry nad listą (daty, zainteresowania, darmowe) -> FilterCriteria ze wszystkich filtrów strony."""
    today = date.today()
    st.session_state.setdefault(_filter_key("when"), DEFAULT_PRESET)
    preset = st.pills(
        "Kiedy", list(DATE_PRESETS), key=_filter_key("when"), format_func=DATE_PRESETS.get,
        label_visibility="collapsed",
    )
    custom = None
    if preset == "custom":
        custom = st.date_input(
            "Zakres dat", value=(today, today + timedelta(days=14)), key=_filter_key("dates"),
            format="DD.MM.YYYY", label_visibility="collapsed",
        )
    with st.container(key="m1_filters_row", horizontal=True, vertical_alignment="center"):
        tags = st.multiselect(
            "Zainteresowania", storage.known_tags(), key=_filter_key("tags"), placeholder="Zainteresowania",
            label_visibility="collapsed",
        )
        free_only = st.toggle("Darmowe", key=_filter_key("free"))
        st.button("", key="m1_f_clear", icon=":material/filter_alt_off:", type="tertiary",
                  on_click=_clear_filters, help="Wyczyść filtry")

    date_from, date_to = date_range_for(preset, today, custom)
    if query is None:
        query = st.session_state.get(_filter_key("query"), "")
    if categories is None:
        categories = list(st.session_state.get(_filter_key("cats")) or [])
    criteria = FilterCriteria(
        query=query or "", categories=categories, date_from=date_from, date_to=date_to,
        tags=tags, free_only=free_only,
    )
    state.set_filters(criteria)
    return criteria


def sort_events(
    events: list[Event], sort: str, *, counts: dict[str, int], center: Place | None,
) -> list[Event]:
    if sort == "popular":
        return sorted(events, key=lambda e: (-counts.get(e.id, 0), e.start))
    if sort == "near":
        origin = center or Place(*PLACES["Rynek Główny"])
        return sorted(events, key=lambda e: (event_distance_km(e, origin), e.start))
    if sort == "cheap":
        return sorted(events, key=lambda e: (e.price_pln is None, e.price_pln or 0, e.start))
    return sorted(events, key=lambda e: (e.start, e.title))


def _select_from_list(event_id: str) -> None:
    state.select_event(event_id)
    st.session_state["m1_right_toggle"] = False          # pokaż panel szczegółów, jeśli był schowany


def _show_more() -> None:
    st.session_state["m1_page"] = st.session_state.get("m1_page", PAGE_SIZE) + PAGE_SIZE


def _thumb_html(event: Event, cls: str = "m1-thumb", img_cls: str = "m1-thumb-img") -> str:
    color = CATEGORY_COLORS[event.category]
    img = ""
    if src := _css_url(event.image_url):
        img = f'<div class="{img_cls}" style="background-image:url(&quot;{src}&quot;)"></div>'
    return f'<div class="{cls}" style="--c:{color}">{_icon(_CATEGORY_ICONS[event.category])}{img}</div>'


def _day_badge(event: Event, today: date) -> str:
    start = event.start.date()
    if start == today:
        return '<span class="m1-badge">dziś</span>'
    if start == today + timedelta(days=1):
        return '<span class="m1-badge">jutro</span>'
    if start < today <= event.end_or_start.date():
        return '<span class="m1-badge">trwa</span>'
    return ""


def _price_html(event: Event) -> str:
    if event.price_pln is None:
        return '<span class="m1-price" style="color:var(--krk-muted);font-weight:600">cena nieznana</span>'
    if event.price_pln == 0:
        return '<span class="m1-price">Wstęp wolny</span>'
    return f'<span class="m1-price">{event.price_pln:.0f} zł<small>/ bilet</small></span>'


def event_card_html(event: Event, *, going: int, distance: float | None, today: date) -> str:
    """Karta na liście (styl job boardu): miniatura, miejsce i termin, tytuł, cena, tagi, stopka."""
    tags = "".join(f'<span class="m1-tag">{html.escape(t)}</span>' for t in event.tags[:3])
    foot_right = ""
    if distance is not None:
        foot_right = f'<span class="right">{_icon("near_me")}{format_distance(distance)}</span>'
    people = (f"{going} {plural_pl(going, 'osoba idzie', 'osoby idą', 'osób idzie')}" if going
              else "Bądź pierwszy")
    return (
        '<div class="m1-card">'
        f"{_thumb_html(event)}"
        '<div class="m1-card-main">'
        f'<div class="m1-card-meta"><span>{_icon("location_on")}{html.escape(event.venue)}</span>'
        f'<span>{_icon("schedule")}{html.escape(format_when(event, today))}</span></div>'
        f'<div class="m1-card-title">{html.escape(event.title)}{_day_badge(event, today)}</div>'
        f"{_price_html(event)}</div>"
        + (f'<div class="m1-tags">{tags}</div>' if tags else "")
        + f'<div class="m1-card-foot">{html.escape(event.meta.label)}<span class="dot"></span>'
        f'<span class="muted">{people}</span>{foot_right}</div>'
        "</div>"
    )


def render_list_header(count: int, location: tuple[str, Place | None, float | None]) -> str:
    """Tytuł listy + licznik wyników + sortowanie. Zwraca wybrany klucz sortowania."""
    name, center, radius = location
    where = f"{format_radius(radius)} od: {html.escape(name)}" if center else "Cały Kraków"
    with st.container(key="m1_list_head", horizontal=True, vertical_alignment="center"):
        st.markdown(
            f'<div class="m1-panel-title">Wydarzenia <span class="m1-count">{count}</span></div>'
            f'<div class="m1-panel-sub m1-where">{_icon("location_on")}{where}</div>',
            unsafe_allow_html=True,
        )
        sort = st.selectbox(
            "Sortuj", list(SORTS), key=_filter_key("sort"), format_func=SORTS.get,
            label_visibility="collapsed", width=172,
        )
    return sort or "soon"


def render_event_list(storage: Storage, events: list[Event], *, selected_id: str | None,
                      center: Place | None) -> None:
    if not events:
        st.markdown(
            f'<div class="m1-empty">{_icon("travel_explore")}<b>Nic tu nie ma</b>'
            "Zmień daty, kategorie albo powiększ promień.</div>",
            unsafe_allow_html=True,
        )
        st.button("Wyczyść filtry", key="m1_empty_clear", icon=":material/filter_alt_off:",
                  on_click=_clear_filters, width="stretch")
        return
    today = date.today()
    counts = storage.attendee_counts()
    shown = events[: st.session_state.get("m1_page", PAGE_SIZE)]
    for event in shown:
        distance = event_distance_km(event, center) if center else None
        with st.container(key=f"m1_card_{event.id}"):
            st.markdown(event_card_html(event, going=counts.get(event.id, 0), distance=distance, today=today),
                        unsafe_allow_html=True)
            st.button(f"Pokaż: {event.title}", key=f"m1_pick_{event.id}",
                      on_click=_select_from_list, args=(event.id,))
    if len(events) > len(shown):
        st.button(f"Pokaż więcej ({len(events) - len(shown)})", key="m1_more", icon=":material/expand_more:",
                  on_click=_show_more, width="stretch")
    st.markdown(state_css(selected_card=selected_id if selected_id in {e.id for e in shown} else None),
                unsafe_allow_html=True)


def category_counts(storage: Storage, criteria: FilterCriteria, center: Place | None,
                    radius_km: float | None) -> dict[Category, int]:
    """Liczba wydarzeń w każdej kategorii przy pozostałych filtrach (jak fasety w wyszukiwarce)."""
    pool = within_radius(storage.list_events(criteria.copy_with(categories=[])), center, radius_km)
    return dict(Counter(e.category for e in pool))


# --------------------------------------------------------------------------- #
# Ostrość mapy — przesuwamy widok tylko po akcjach spoza mapy
# --------------------------------------------------------------------------- #

def map_focus(storage: Storage, events: list[Event], selected_id: str | None,
              center: Place | None, radius_km: float | None) -> MapFocus | None:
    """Nowy wybór z listy / rekomendacji / profilu -> mapa jedzie do eventu; zmiana promienia -> do okręgu.

    Klik w pinezkę NIE przesuwa mapy (`note_map_selection`). Mikroskopijne przesunięcie (nonce) sprawia, że
    ponowny wybór tego samego miejsca też przesuwa widok (streamlit-folium reaguje tylko na zmianę).
    """
    ss = st.session_state
    loc = (center, radius_km)
    if loc != ss.get("m1_focus_loc"):
        ss["m1_focus_loc"] = loc
        if center is not None and radius_km:
            ss["m1_focus_n"] = ss.get("m1_focus_n", 0) + 1
            n = ss["m1_focus_n"]
            zoom = zoom_for_radius(radius_km) + n * 1e-6
            ss["m1_focus"] = MapFocus(center.lat + n * 1e-9, center.lon, zoom)
    if selected_id != ss.get("m1_focus_sel"):
        ss["m1_focus_sel"] = selected_id
        if selected_id and (event := storage.get_event(selected_id)):
            lat, lon = pin_positions(events).get(event.id, (event.lat, event.lon))
            ss["m1_focus_n"] = ss.get("m1_focus_n", 0) + 1
            ss["m1_focus"] = MapFocus(lat + ss["m1_focus_n"] * 1e-9, lon)
    return ss.get("m1_focus")


def note_map_selection(event_id: str) -> None:
    """Wybór kliknięciem pinezki: bez przesuwania mapy, panel szczegółów się otwiera."""
    state.select_event(event_id)
    st.session_state["m1_focus_sel"] = event_id
    st.session_state["m1_right_toggle"] = False


# --------------------------------------------------------------------------- #
# Prawy panel — szczegóły wydarzenia / polecane
# --------------------------------------------------------------------------- #

def _close_panel() -> None:
    state.select_event(None)


def _fact(icon: str, main: str, sub: str = "") -> str:
    small = f"<small>{sub}</small>" if sub else ""
    return f'<div class="m1-fact"><span class="ico">{_icon(icon)}</span><div>{main}{small}</div></div>'


def _source_label(event: Event) -> str:
    if event.source.startswith("scraper:"):
        return "źródło: " + event.source.split(":", 1)[1]
    return {"user": "dodane przez użytkownika", "mock": "demo"}.get(event.source, event.source)


def render_event_panel(storage: Storage, user: User, event: Event | None) -> None:
    if event is None:
        st.markdown(
            '<div class="m1-panel-title">Odkrywaj</div>'
            '<div class="m1-panel-sub">Kliknij pinezkę albo kartę na liście, żeby zobaczyć szczegóły '
            "i osoby, które też idą.</div>",
            unsafe_allow_html=True,
        )
        if FEATURES["recommendations"]:
            with st.container(key="m1_recs"):
                render_recommendations(storage, user)
        return

    meta = event.meta
    with st.container(key="m1_detail_head", horizontal=True, vertical_alignment="center"):
        st.markdown(f'<div class="m1-panel-sub" style="margin:0">{html.escape(_source_label(event))}</div>',
                    unsafe_allow_html=True)
        st.space("stretch")
        if event.url:
            st.link_button("", event.url, icon=":material/open_in_new:", help="Strona wydarzenia")
        st.button("", key="m1_close_panel", icon=":material/close:", on_click=_close_panel, help="Zamknij")

    color = CATEGORY_COLORS[event.category]
    img = ""
    if src := _css_url(event.image_url):
        img = f'<div class="m1-hero-img" style="background-image:url(&quot;{src}&quot;)"></div>'
    icon = _icon(_CATEGORY_ICONS[event.category])
    st.markdown(
        f'<div class="m1-hero" style="--c:{color}">{icon}{img}'
        f'<span class="m1-hero-badge">{icon}{html.escape(meta.label)}</span>'
        "</div>"
        f'<div class="m1-detail-title">{html.escape(event.title)}</div>',
        unsafe_allow_html=True,
    )

    attendees = len(storage.list_attendees(event.id))
    price = format_price(event.price_pln)
    price_html = f'<span class="price">{html.escape(price)}</span>' if event.price_pln is not None else price
    facts = [
        _fact("calendar_month", f"<b>{html.escape(format_when(event))}</b>", full_date(event)),
        _fact("location_on", f"<b>{html.escape(event.venue)}</b>", html.escape(event.address)),
        _fact("confirmation_number", price_html,
              f"{attendees} {plural_pl(attendees, 'osoba zapisana', 'osoby zapisane', 'osób zapisanych')}"),
    ]
    st.markdown(f'<div class="m1-facts">{"".join(facts)}</div>', unsafe_allow_html=True)

    render_attendance_controls(storage, event, user)
    render_event_chat_entry(storage, event.id, user)    # M5: zaproszenia · czat grupy | czat wydarzenia
    if event.description:
        st.markdown(f'<div class="m1-desc">{html.escape(event.description)}</div>', unsafe_allow_html=True)

    st.markdown(f'<div class="m1-section">{_icon("handshake")} Pasujące osoby</div>', unsafe_allow_html=True)
    matches = match_for_event(storage, user, event.id, limit=MAX_MATCHES_IN_PANEL)
    if not matches:
        st.caption("Nikt jeszcze się nie zapisał (albo nie chce być widoczny). Bądź pierwszy!")
    with st.container(key="m1_matches"):
        for match in matches:
            render_user_card(match.user, match, key=f"m1_match_{event.id}_{match.user.id}")
