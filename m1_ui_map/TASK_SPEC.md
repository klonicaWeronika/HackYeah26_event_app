# TASK_SPEC — M1: Layout Streamlit & Mapa (UI Shell + integracja)

| | |
|---|---|
| **Właściciel** | _Dev 1_ (pełni też rolę **integratora** — właściciel `app.py`) |
| **Folder** | `m1_ui_map/` + `app.py` + `.streamlit/config.toml` |
| **Priorytet modułu** | CORE |
| **Korzysta z** | `shared/models.py`, `shared/storage.py`, `shared/state.py`, `shared/formatting.py`, `shared/config.py` |
| **Dostarcza dla** | wszystkich: szkielet strony, w który wpinają się M3/M4/M5 (i M2 opcjonalnie) |
| **Sandbox** | `streamlit run app.py` (aplikacja = sandbox M1) |
| **Testy** | `pytest m1_ui_map` |

---

## 1. Cel

Szybki, czytelny ekran główny: mapa Krakowa z pinezkami wydarzeń, filtry po lewej, szczegóły + dopasowane osoby po prawej. Kliknięcie pinezki ma działać natychmiast i bez „skakania” mapy.

## 2. Zakres

### 2.1 Stan wyjściowy (działa w szkielecie)

- `app.py` składa moduły; routing środkowego obszaru po `state.current_view()` (MAP / CHAT / PROFILE_EDIT / PROFILE_VIEW / ADD_EVENT).
- `layout.render_header` — awatar + nazwa + popover „⚙️ Opcje” (edycja profilu, „zaloguj jako”, reset demo).
- `layout.render_filters` — szukajka, kategorie (`st.pills`), zakres dat, tagi, „tylko darmowe” → `FilterCriteria`.
- `map_view.render_map` — folium + `st_folium`, pinezki w kolorze kategorii, rozsuwanie eventów w tym samym miejscu, klik → `event_id`.
- `layout.render_event_panel` — szczegóły, „Idę!” (M5), przycisk czatu, lista dopasowań (M4 + karty M3), rekomendacje (M4) gdy nic nie wybrano.

### 2.2 Zadania atomowe

| ID | Zadanie | Prio | Est. | Gotowe gdy |
|----|---------|------|------|------------|
| M1-01 | Kickoff: uruchomienie, ustalenie nazwy/kolorów (`shared/config.py`, `.streamlit/config.toml`) | MUST | 0.5 h | Każdy w zespole odpalił `app.py` lokalnie |
| M1-02 | Header jako cienki pasek: wyrównanie, popover zamyka się po akcji (`st.rerun()` po kliknięciu), mniejsze paddingi | MUST | 1.5 h | Header ≤ 56 px wysokości, akcje z popovera działają jednym kliknięciem |
| M1-03 | Filtry: presety dat (Dziś / Jutro / Weekend / 7 dni) obok `date_input`, licznik wyników, obsługa niepełnego zakresu dat | MUST | 2 h | Każdy preset ustawia poprawny `FilterCriteria`; pusty wynik pokazuje komunikat zamiast pustej mapy |
| M1-04 | Mapa: wyróżnienie wybranej pinezki **bez resetu widoku** (`feature_group_to_add` w `st_folium`), wycentrowanie na evencie wybranym z rekomendacji (`center=`), `MarkerCluster` gdy > 80 eventów | MUST | 3 h | Klik w pinezkę: panel się otwiera, mapa nie zmienia zoomu; wybór z listy przesuwa mapę |
| M1-05 | Prawy panel: dopracowanie hierarchii (tytuł, kiedy/gdzie/cena, CTA), stany puste, scroll tylko w panelu | MUST | 2 h | Panel czytelny przy 0, 1 i 8 dopasowaniach; nic nie „wypycha” mapy |
| M1-06 | `safe_render(fn, *args)` — wrapper łapiący wyjątki modułów M2–M5 i pokazujący `st.error` w ich miejscu | MUST | 1 h | Celowy `raise` w M4 nie wywraca strony — reszta działa |
| M1-07 | Wydajność: przełącznik debug z czasem reruna (`time.perf_counter`) w sidebarze; budowa mapy cache'owana po krotce ID eventów (`st.cache_resource`) | SHOULD | 1.5 h | Rerun po kliknięciu pinezki < 300 ms (lokalnie, 36–300 eventów) |
| M1-08 | Widok „Lista” jako alternatywa mapy (`st.segmented_control` Mapa / Lista) — tabela/karty eventów z przyciskiem „Pokaż” | SHOULD | 1.5 h | Lista respektuje filtry, klik ustawia `select_event` |
| M1-09 | Integracja na checkpointach: merge gałęzi modułów, przełączanie `FEATURES`, aktualizacja smoke testu | SHOULD | 1.5 h | `pytest` zielony na `main` po każdym checkpoincie |
| M1-10 | Mobile/wąski ekran: sidebar domyślnie zwinięty < 900 px, panel pod mapą; sprawdzenie dark mode | COULD | 1.5 h | Demo da się pokazać na telefonie bez poziomego scrolla |
| M1-11 | Skrypt klikania demo (ścieżka z ARCHITECTURE.md §11) + bugfix | MUST | 1 h | Ścieżka demo przechodzi 3× pod rząd bez błędu |

### 2.3 Poza zakresem

- Logika matchingu (M4), formularz profilu i karty osób (M3), czat i przycisk „Idę!” (M5), pozyskiwanie eventów (M2).
- M1 **nie** pisze do `storage` poza resetem demo — tylko czyta i składa widoki.

## 3. Kontrakty

### 3.1 Wejście (z `shared/` i modułów)

```python
from shared.storage import get_storage, Storage          # list_events(criteria), get_event, list_attendees, count_messages
from shared.models import Event, FilterCriteria, Category, CATEGORY_META, KRAKOW_CENTER, event_room_id
from shared import state                                  # init, current_view, go_to, select_event, set_filters
from shared.formatting import format_when, format_price
# moduły:
from m3_profile.views import avatar_html, render_user_card, render_user_switcher, render_profile_editor, render_profile_view
from m4_matching.engine import match_for_event
from m4_matching.widgets import render_recommendations
from m5_chat.chat_view import render_chat_room, render_attendance_controls
```

### 3.2 Wyjście — publiczne API

```python
# m1_ui_map/map_view.py
pin_positions(events: list[Event]) -> dict[str, tuple[float, float]]
find_clicked_event(click: dict, positions: dict[str, tuple[float, float]]) -> str | None
build_map(events: list[Event], positions: dict[str, tuple[float, float]]) -> folium.Map
render_map(events: list[Event]) -> str | None          # event_id NOWO klikniętej pinezki
reset_map() -> None

# m1_ui_map/layout.py
inject_css() -> None
render_header(storage: Storage, user: User) -> None
render_filters(storage: Storage) -> FilterCriteria
render_event_panel(storage: Storage, user: User, event: Event | None) -> None
```

### 3.3 Stan sesji

| Klucz / funkcja `shared.state` | Czyta | Pisze |
|---|---|---|
| `current_view()` / `go_to()` | ✅ | ✅ (przyciski w panelu i headerze) |
| `selected_event_id()` / `select_event()` | ✅ | ✅ (klik pinezki, zamknięcie panelu) |
| `set_filters()` | — | ✅ (co rerun) |
| `current_user_id()` | ✅ | — |

Prywatne: `m1_f_*` (widgety filtrów), `m1_map_nonce`, `m1_last_click`.

### 3.4 Pliki modułu

`app.py`, `m1_ui_map/*`, `.streamlit/config.toml`.

## 4. Niezależne testowanie (mocki)

1. `streamlit run app.py` — od razu działa na mockach (36 eventów, 12 osób). Świeże daty: `python -m shared.storage --reset`.
2. `pytest m1_ui_map` — rozsuwanie pinezek, mapowanie kliku na event, liczba markerów, **smoke test całej aplikacji** (`AppTest`).
3. Obciążenie: w sandboxie/REPL wygeneruj 300 eventów (`event.copy_with(id=..., lat=..., lon=...)`) do `Storage(":memory:")` i zmierz czas reruna.
4. Dwie karty przeglądarki: `?user=u_ola` i `?user=u_kuba` — panel dopasowań różni się per osoba.

## 5. Definition of Done (demo)

- [ ] Wszystkie MUST zrobione, `pytest` zielony.
- [ ] Layout zgodny z wireframe: cienki header (awatar + nazwa | opcje), filtry w sidebarze, mapa w centrum, panel po prawej.
- [ ] Klik pinezki → panel w < 300 ms, mapa nie resetuje zoomu.
- [ ] Zmiana filtra natychmiast zmienia pinezki i licznik.
- [ ] Panel po prawej pokazuje szczegóły, zapis, dopasowane osoby i przycisk czatu.
- [ ] Awaria jednego modułu nie wywraca strony (`safe_render`).

## 6. Ryzyka i plan B

| Ryzyko | Sygnał ostrzegawczy | Plan B |
|---|---|---|
| `st_folium` remontuje mapę i resetuje zoom | Po kliknięciu mapa „skacze” | `feature_group_to_add` dla warstwy wyróżnienia; ostatecznie `st.pydeck_chart(..., on_select="rerun")` (natywna selekcja Streamlit) |
| Kafelki mapy nie ładują się (brak internetu / limit) | Szare tło mapy | Hotspot z telefonu; kafelki CartoDB **wymagają klucza API od folium 0.20** — zostajemy przy OpenStreetMap |
| Wolne reruny przy setkach eventów | Debug timer > 500 ms | `MarkerCluster`, cache mapy, ograniczenie zakresu dat domyślnie do 14 dni |
| Konflikty w `app.py` | Merge conflicts | Tylko M1 edytuje `app.py`; inni dostarczają funkcje `render_*` |

## 7. Punkty synchronizacji

| Kiedy | Co musi być na `main` |
|---|---|
| H1 | Wszyscy odpalili `app.py`; kontrakt zamrożony |
| H6 | M1-02..M1-06 + pierwsze merge'e modułów; ścieżka demo klikalna end-to-end |
| H12 | Prawdziwe dane z M2 na mapie; M1-07/08 |
| H18 | Feature freeze; flagi `FEATURES` ustawione na demo |
| H21 | Code freeze, tag `demo-v1` |
