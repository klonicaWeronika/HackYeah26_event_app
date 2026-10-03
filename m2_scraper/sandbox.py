"""M2 sandbox — podgląd wyniku źródła BEZ zapisu do bazy:  streamlit run m2_scraper/sandbox.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from m2_scraper.run import collect  # noqa: E402
from m2_scraper.sources import SOURCES  # noqa: E402
from shared.models import Event  # noqa: E402

st.set_page_config(page_title="M2 sandbox", layout="wide")
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
