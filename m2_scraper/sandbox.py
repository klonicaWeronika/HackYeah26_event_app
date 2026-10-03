"""M2 sandbox — podgląd wyniku źródła BEZ zapisu do bazy:  streamlit run m2_scraper/sandbox.py

Tryb „Formularz” pokazuje M2-09 (Dodaj wydarzenie) na bazie w pamięci — data/app.db pozostaje nietknięta.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from m2_scraper.run import collect  # noqa: E402
from m2_scraper.sources import SOURCES  # noqa: E402
from shared.models import Event  # noqa: E402
from shared.storage import Storage  # noqa: E402

st.set_page_config(page_title="M2 sandbox", layout="wide")
FORM_MODE = "Formularz „Dodaj wydarzenie”"
mode = st.sidebar.radio("Tryb", ["Podgląd źródła", FORM_MODE], key="m2_sandbox_mode")


@st.cache_resource
def sandbox_storage() -> Storage:
    return Storage(":memory:")                 # mocki + to, co dodasz formularzem (do restartu sandboxa)


if mode == FORM_MODE:
    from m2_scraper.add_event_form import render_add_event_form
    from shared import state

    state.init()
    store = sandbox_storage()
    render_add_event_form(store, store.get_user(state.current_user_id()))
    added = [e for e in store.list_events() if e.source == "user"]
    st.divider()
    st.caption(f"Dodane w tej sesji sandboxa (baza w pamięci): {len(added)}")
    if added:
        st.map([{"lat": e.lat, "lon": e.lon} for e in added])
        st.dataframe([{"tytuł": e.title, "kategoria": e.category.value, "start": e.start, "koniec": e.end,
                       "miejsce": e.venue, "adres": e.address, "tagi": ", ".join(e.tags), "cena": e.price_pln,
                       "autor": e.created_by} for e in added], width="stretch")
    st.stop()

name = st.sidebar.selectbox("Źródło", list(SOURCES))


@st.cache_data(ttl=600, show_spinner="Pobieram i parsuję (scrapery pracują na cache HTML)…")
def load(source_name: str) -> list[Event]:
    return collect(SOURCES[source_name]())


if st.sidebar.button("Odśwież", key="m2_refresh"):
    load.clear()

events = load(name)
st.metric("Poprawnych eventów (w granicach Krakowa)", len(events))
st.map([{"lat": e.lat, "lon": e.lon} for e in events])
st.dataframe(
    [{"id": e.id, "tytuł": e.title, "kategoria": e.category.value, "start": e.start, "koniec": e.end,
      "miejsce": e.venue, "tagi": ", ".join(e.tags), "cena": e.price_pln, "opis": e.description[:120],
      "url": e.url, "źródło": e.source} for e in events],
    width="stretch",
)
