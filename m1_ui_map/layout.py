"""
M1 — layout aplikacji: górny pasek, lewy panel filtrów, prawy panel szczegółów wydarzenia.

Układ (wireframe):
    ┌─ logo ─┬──────── header: awatar + imię ───────────────── Menu ┐
    │ sidebar:  │  MAPA z pinezkami  /  Live Chat  │ prawy panel:  │
    │ filtry    │  (View.MAP / View.CHAT / ...)    │ szczegóły +   │
    │           │                                  │ dopasowania + │
    │           │                                  │ przycisk czatu│
    └───────────┴──────────────────────────────────┴───────────────┘

Styl: ikony Material (`:material/...:`) zamiast emoji, etykiety sekcji kapitalikami, kolory przez
przezroczystość -> ten sam CSS działa w jasnym i ciemnym motywie.
"""

from __future__ import annotations

import html
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from m1_ui_map.map_view import MAP_HEIGHT, reset_map
from m3_profile.views import avatar_html, render_user_card, render_user_switcher
from m4_matching.engine import match_for_event, plural_pl
from m4_matching.widgets import render_recommendations
from m5_chat.chat_view import render_attendance_controls
from shared import state
from shared.config import APP_TAGLINE, FEATURES, MAX_MATCHES_IN_PANEL
from shared.formatting import format_price, format_when
from shared.models import CATEGORY_META, Category, Event, FilterCriteria, User, event_room_id
from shared.state import View
from shared.storage import Storage

_ASSETS = Path(__file__).resolve().parent / "assets"
LOGO_PATH = str(_ASSETS / "logo.svg")             # znak + „KRK Razem” (sidebar)
LOGO_MARK_PATH = str(_ASSETS / "logo_mark.svg")   # sam znak (zwinięty sidebar, favicon)

_MENU_KEY = "m1_menu"                             # stan popovera „Menu” (True = otwarte)
_FILTER_FIELDS = ("query", "cats", "dates", "tags", "free")

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

_CSS = """
<style>
/* --- Chrome Streamlita ----------------------------------------------------------------------------
   Pasek narzędzi (stToolbar) ma 60 px i leży nad całą górą obszaru głównego -> przepuszczamy kliki
   do naszego headera; przyciski samego paska (np. rozwinięcie sidebara) dalej działają. */
header[data-testid="stHeader"] {background: transparent; pointer-events: none;}
header[data-testid="stHeader"] button, header[data-testid="stHeader"] a {pointer-events: auto;}
[data-testid="stStatusWidget"] {visibility: hidden;}
.block-container {padding-top: 1rem; padding-bottom: 0.5rem;}

/* --- Sidebar ------------------------------------------------------------------------------------ */
[data-testid="stSidebarHeader"] {padding-bottom: 0.25rem;}
[data-testid="stSidebarUserContent"] {padding-top: 0;}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
  font-size: 0.7rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.55;
}
[data-testid="stSidebar"] [data-testid="stCheckbox"] [data-testid="stWidgetLabel"] p {
  font-size: 0.9rem; font-weight: 500; letter-spacing: 0; text-transform: none; opacity: 0.9;
}
.m1-tagline {font-size: 0.85rem; opacity: 0.6; margin-top: -0.4rem;}
.m1-section {font-size: 1.05rem; font-weight: 650; letter-spacing: -0.01em;}
.st-key-m1_f_clear button {padding: 0 0.25rem; min-height: 0; font-size: 0.85rem; opacity: 0.75;}
.st-key-m1_f_clear button:hover {opacity: 1;}

/* --- Header ------------------------------------------------------------------------------------- */
.st-key-m1_header {min-height: 44px;}
.m1-header {display: flex; align-items: center; gap: 12px; min-width: 0;}
.m1-header > div:last-child {min-width: 0;}
.m1-hello {font-weight: 650; font-size: 1rem; line-height: 1.25; letter-spacing: -0.01em;
           white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.m1-plans {font-size: 0.8rem; opacity: 0.6; line-height: 1.25;
           white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}

/* --- Menu (popover) ----------------------------------------------------------------------------- */
[data-testid="stPopoverBody"]:has(.st-key-m1_menu_body) {min-width: 300px; padding: 0.4rem;}
/* Pozycje menu: przyciski M1 (tertiary) i „Nowy profil” z przełącznika M3 wyglądają tak samo. */
.st-key-m1_menu_body [data-testid="stBaseButton-tertiary"],
.st-key-m1_menu_body .st-key-m3_user_switch_new button {
  width: 100%; justify-content: flex-start; padding: 0.5rem 0.6rem; border-radius: 0.5rem;
  border: none; background: transparent; box-shadow: none; min-height: 0;
}
.st-key-m1_menu_body button > div {justify-content: flex-start;}
.st-key-m1_menu_body [data-testid="stBaseButton-tertiary"]:hover,
.st-key-m1_menu_body .st-key-m3_user_switch_new button:hover {background: rgba(128, 128, 128, 0.12);}
.st-key-m1_menu_body [data-testid="stWidgetLabel"] p {
  font-size: 0.7rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.55;
}
.st-key-m1_menu_body .st-key-m3_user_switch,
.st-key-m1_menu_body [data-testid="stCaptionContainer"] {padding: 0.25rem 0.6rem 0;}
.m1-menu-user {
  display: flex; align-items: center; gap: 10px; padding: 0.4rem 0.6rem 0.6rem; margin-bottom: 0.35rem;
  border-bottom: 1px solid rgba(128, 128, 128, 0.2);
}
.m1-menu-user .m1-hello {font-size: 0.95rem;}
.m1-sep {height: 1px; background: rgba(128, 128, 128, 0.2); margin: 0.35rem 0;}
.st-key-m1_menu_reset [data-testid="stBaseButton-tertiary"] {color: #D9431A;}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def category_label(category: Category) -> str:
    """Etykieta kategorii w filtrach: ikona Material + nazwa PL (bez emoji)."""
    return f":material/{_CATEGORY_ICONS[category]}: {CATEGORY_META[category].label}"


def plans_caption(going: int) -> str:
    """Podpis pod imieniem w headerze: '1 wydarzenie w planach', '14 wydarzeń w planach'."""
    if going == 0:
        return "Brak planów — wybierz coś na mapie"
    return f"{going} {plural_pl(going, 'wydarzenie', 'wydarzenia', 'wydarzeń')} w planach"


# --------------------------------------------------------------------------- #
# Górny pasek + menu
# --------------------------------------------------------------------------- #

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


def render_header(storage: Storage, user: User) -> None:
    going = len(storage.list_user_attendance(user.id))
    with st.container(
        key="m1_header", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
    ):
        st.markdown(_user_html(user, 40, plans_caption(going)), unsafe_allow_html=True)
        _render_menu(storage, user)


# --------------------------------------------------------------------------- #
# Lewy panel — filtry
# --------------------------------------------------------------------------- #

def _filter_key(field: str) -> str:
    """Klucz widgetu filtra z numerem wersji: „Wyczyść” podbija wersję -> widgety montują się od nowa
    z wartościami domyślnymi (samo usunięcie kluczy zostawiało w przeglądarce stare wartości)."""
    return f"m1_f_{field}_{st.session_state.get('m1_f_ver', 0)}"


def _clear_filters() -> None:
    for field in _FILTER_FIELDS:
        st.session_state.pop(_filter_key(field), None)
    st.session_state["m1_f_ver"] = st.session_state.get("m1_f_ver", 0) + 1


def render_filters(storage: Storage) -> FilterCriteria:
    today = date.today()
    st.logo(LOGO_PATH, icon_image=LOGO_MARK_PATH, size="large")
    with st.sidebar:
        st.markdown(f'<div class="m1-tagline">{html.escape(APP_TAGLINE)}</div>', unsafe_allow_html=True)
        st.space("small")
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            st.markdown('<div class="m1-section">Filtry</div>', unsafe_allow_html=True)
            st.button(
                "Wyczyść", key="m1_f_clear", icon=":material/filter_alt_off:", type="tertiary",
                on_click=_clear_filters, help="Przywróć domyślne filtry",
            )
        count_slot = st.empty()

        query = st.text_input(
            "Szukaj", key=_filter_key("query"), placeholder="Wydarzenie, miejsce, tag…",
            icon=":material/search:", label_visibility="collapsed",
        )
        categories = st.pills(
            "Kategorie", list(Category), selection_mode="multi", key=_filter_key("cats"),
            format_func=category_label,
        )
        dates = st.date_input(
            "Kiedy", value=(today, today + timedelta(days=14)), key=_filter_key("dates"), format="DD.MM.YYYY",
        )
        tags = st.multiselect(
            "Zainteresowania", storage.known_tags(), key=_filter_key("tags"), placeholder="Wybierz tagi",
        )
        free_only = st.toggle("Tylko darmowe", key=_filter_key("free"))

    date_range = list(dates) if isinstance(dates, (list, tuple)) else [dates]
    criteria = FilterCriteria(
        query=query,
        categories=categories or [],
        date_from=date_range[0] if date_range else None,
        date_to=date_range[1] if len(date_range) > 1 else (date_range[0] if date_range else None),
        tags=tags,
        free_only=free_only,
    )
    state.set_filters(criteria)
    # Licznik nad polami filtrów (slot z góry). Filtr snapshotu w RAM to ~1 ms — bez kosztu dla reruna.
    count_slot.caption(f"Na mapie: **{len(storage.list_events(criteria))}** wydarzeń")
    return criteria


# --------------------------------------------------------------------------- #
# Prawy panel — szczegóły wydarzenia
# --------------------------------------------------------------------------- #

def _close_panel() -> None:
    state.select_event(None)
    reset_map()


def render_event_panel(storage: Storage, user: User, event: Event | None) -> None:
    with st.container(height=MAP_HEIGHT, border=False):
        if event is None:
            st.info("👈 Kliknij pinezkę na mapie, aby zobaczyć szczegóły wydarzenia i osoby, które się na nie wybierają.")
            if FEATURES["recommendations"]:
                render_recommendations(storage, user)
            return

        meta = event.meta
        col_badge, col_close = st.columns([5, 1], vertical_alignment="center")
        col_badge.badge(f"{meta.emoji} {meta.label}", color="primary")
        col_close.button("✕", key="m1_close_panel", on_click=_close_panel, type="tertiary", help="Zamknij")

        st.markdown(f"### {event.title}")
        st.markdown(
            f"🗓️ **{format_when(event)}**  \n"
            f"📍 **{event.venue}**, {event.address}  \n"
            f"💸 {format_price(event.price_pln)} · 👥 {len(storage.list_attendees(event.id))} zapisanych"
        )
        if event.description:
            st.caption(event.description)
        if event.url:
            st.link_button("Strona wydarzenia ↗", event.url)

        render_attendance_controls(storage, event, user)

        room_id = event_room_id(event.id)
        st.button(
            f"💬 Czat wydarzenia ({storage.count_messages(room_id)})",
            key="m1_open_chat", width="stretch",
            on_click=state.go_to, args=(View.CHAT,), kwargs={"room_id": room_id},
        )

        st.markdown("#### 🤝 Pasujące osoby")
        matches = match_for_event(storage, user, event.id, limit=MAX_MATCHES_IN_PANEL)
        if not matches:
            st.caption("Nikt jeszcze się nie zapisał (albo nie chce być widoczny). Bądź pierwszy!")
        for match in matches:
            render_user_card(match.user, match, key=f"m1_match_{event.id}_{match.user.id}")
