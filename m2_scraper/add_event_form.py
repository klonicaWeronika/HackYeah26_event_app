"""
M2 (opcjonalne) — formularz dodawania własnego wydarzenia przez użytkownika.

Włączany flagą FEATURES["add_event"] w shared/config.py, gdy spełni DoD z TASK_SPEC.md.
Kontrakt: zapisuje Event(source="user", created_by=user.id) przez storage.upsert_event().

Zapis idzie w callbacku (przed rerunem skryptu) -> w tym samym przebiegu app.py pokazuje mapę z nową
pinezką i otwarty panel wydarzenia, bez dodatkowego st.rerun(). Logika i walidacja: m2_scraper/user_events.py.
Klucze sesji prywatne dla modułu: m2_*.
"""

from __future__ import annotations

from datetime import date, time, timedelta

import folium
import streamlit as st
from streamlit_folium import st_folium

from m2_scraper.normalize import extract_tags
from m2_scraper.user_events import (
    DESCRIPTION_MAX,
    MAX_TAGS,
    TITLE_MAX,
    Place,
    PlaceMode,
    build_user_event,
    known_places,
    resolve_place,
)
from shared import state
from shared.models import CATEGORY_META, KRAKOW_CENTER, Category, User
from shared.state import View
from shared.storage import Storage

_FIELD = "m2_f_"                 # prefiks pól formularza (czyszczone po zapisie)
_ERRORS = "m2_errors"
_PICKED = "m2_picked"            # (lat, lon) z kliknięcia na mapie
_LAST_CLICK = "m2_last_click"


def _category_label(category: Category) -> str:
    meta = CATEGORY_META[category]
    return f"{meta.emoji} {meta.label}"


def _clear_form() -> None:
    ss = st.session_state
    for key in [k for k in ss if str(k).startswith(_FIELD)] + [_PICKED, _LAST_CLICK, _ERRORS]:
        ss.pop(key, None)


def _current_place() -> tuple[Place | None, str | None]:
    ss = st.session_state
    mode = ss.get(_FIELD + "mode", PlaceMode.KNOWN)
    return resolve_place(
        mode, known_name=ss.get(_FIELD + "known"), venue_name=ss.get(_FIELD + "venue", ""),
        address=ss.get(_FIELD + "address", ""), picked=ss.get(_PICKED),
    )


def _save(storage: Storage, user_id: str) -> None:
    ss = st.session_state
    place, place_error = _current_place()
    event, errors = build_user_event(
        user_id, title=ss.get(_FIELD + "title", ""), category=ss.get(_FIELD + "category"),
        day=ss.get(_FIELD + "date"), start_time=ss.get(_FIELD + "time"), duration_h=ss.get(_FIELD + "duration"),
        place=place, tags=ss.get(_FIELD + "tags"), free=ss.get(_FIELD + "free", False),
        price=ss.get(_FIELD + "price"), description=ss.get(_FIELD + "desc", ""), url=ss.get(_FIELD + "url", ""),
    )
    if place_error:
        errors = [place_error] + [e for e in errors if e != "Wskaż miejsce wydarzenia."]
    if errors:
        ss[_ERRORS] = errors
        return
    storage.upsert_event(event)
    _clear_form()
    state.select_event(event.id)                 # prawy panel od razu pokazuje nowe wydarzenie
    state.go_to(View.MAP)
    hint = "" if state.get_filters().matches(event) else " Nie pasuje do bieżących filtrów mapy — szczegóły po prawej."
    st.toast(f"Dodano „{event.title}”.{hint}", icon="✅")


def _back() -> None:
    _clear_form()
    state.go_to(View.MAP)


def _render_pick_map(place: Place | None) -> None:
    """Mapa do wskazania miejsca: klik -> m2_picked; pokazuje wybrany punkt."""
    fmap = folium.Map(location=(place.lat, place.lon) if place else KRAKOW_CENTER, zoom_start=15 if place else 13,
                      tiles="OpenStreetMap")
    if place:
        folium.Marker((place.lat, place.lon), tooltip=place.venue, icon=folium.Icon(color="red")).add_to(fmap)
    output = st_folium(fmap, key="m2_pick_map", height=320, use_container_width=True,
                       returned_objects=["last_clicked"])
    click = (output or {}).get("last_clicked")
    if click and click != st.session_state.get(_LAST_CLICK):      # st_folium zwraca ostatni klik co rerun
        st.session_state[_LAST_CLICK] = click
        st.session_state[_PICKED] = (click["lat"], click["lng"])
        st.rerun()                                                 # odśwież pinezkę w wybranym punkcie


def render_add_event_form(storage: Storage, user: User) -> None:
    ss = st.session_state
    st.subheader("➕ Dodaj wydarzenie")
    st.caption("Wydarzenie od razu pojawi się na mapie — inni zobaczą je i będą mogli dołączyć.")

    col_title, col_cat = st.columns([3, 2])
    col_title.text_input("Tytuł *", key=_FIELD + "title", max_chars=TITLE_MAX,
                         placeholder="np. Wieczór planszówek na Kazimierzu")
    col_cat.selectbox("Kategoria *", list(Category), index=list(Category).index(Category.MEETUP),
                      format_func=_category_label, key=_FIELD + "category")

    col_date, col_time, col_dur = st.columns(3)
    col_date.date_input("Data *", value=date.today(), min_value=date.today(), format="DD.MM.YYYY",
                        key=_FIELD + "date")
    col_time.time_input("Godzina *", value=time(19, 0), step=timedelta(minutes=15), key=_FIELD + "time")
    col_dur.number_input("Czas trwania (godz.)", min_value=0.5, max_value=24.0, value=2.0, step=0.5,
                         key=_FIELD + "duration")

    mode = st.radio("Miejsce *", PlaceMode.ALL, horizontal=True, key=_FIELD + "mode")
    if mode == PlaceMode.KNOWN:
        st.selectbox("Znane miejsce", list(known_places()), index=None, placeholder="Zacznij pisać nazwę…",
                     key=_FIELD + "known", label_visibility="collapsed")
    elif mode == PlaceMode.ADDRESS:
        col_venue, col_addr = st.columns(2)
        col_venue.text_input("Nazwa miejsca", key=_FIELD + "venue", placeholder="np. Kawiarnia Bunkier")
        col_addr.text_input("Adres", key=_FIELD + "address", placeholder="np. pl. Szczepański 3a")
    else:
        st.text_input("Nazwa miejsca (opcjonalnie)", key=_FIELD + "venue", placeholder="np. Bulwary przy Wawelu")

    place, place_error = _current_place()
    if mode == PlaceMode.MAP:
        _render_pick_map(place)
    if place:
        st.caption(f"📍 {place.venue}" + (f", {place.address}" if place.address else ""))
    elif mode == PlaceMode.ADDRESS and (ss.get(_FIELD + "venue") or ss.get(_FIELD + "address")):
        st.warning(place_error)

    st.multiselect("Zainteresowania (tagi)", storage.known_tags(), key=_FIELD + "tags", max_selections=MAX_TAGS,
                   accept_new_options=True, placeholder="Wybierz albo wpisz własne",
                   help="Po tagach dopasowujemy osoby o podobnych zainteresowaniach.")
    if not ss.get(_FIELD + "tags"):
        suggested = extract_tags(f"{ss.get(_FIELD + 'title', '')} {ss.get(_FIELD + 'desc', '')}")[:MAX_TAGS]
        if suggested:
            st.caption("Bez wybranych tagów dobierzemy automatycznie: " + ", ".join(suggested))

    col_free, col_price = st.columns([1, 2], vertical_alignment="bottom")
    free = col_free.checkbox("Wstęp wolny", key=_FIELD + "free")
    col_price.number_input("Cena (zł)", min_value=0.0, value=None, step=5.0, disabled=free,
                           placeholder="puste = nieznana", key=_FIELD + "price")
    st.text_area("Opis", key=_FIELD + "desc", max_chars=DESCRIPTION_MAX, height="content",
                 placeholder="Co się będzie działo? Dla kogo?")
    st.text_input("Link (opcjonalnie)", key=_FIELD + "url", placeholder="https://…")

    if errors := ss.pop(_ERRORS, None):
        st.error("\n".join(f"- {e}" for e in errors))

    col_save, col_back = st.columns(2)
    col_save.button("Zapisz wydarzenie", type="primary", on_click=_save, args=(storage, user.id),
                    key="m2_save", width="stretch")
    col_back.button("← Wróć do mapy", on_click=_back, key="m2_back", width="stretch")
