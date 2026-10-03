# TASK_SPEC — M2: Scraper eventów i zasilanie bazy

| | |
|---|---|
| **Właściciel** | _Dev 2_ |
| **Folder** | `m2_scraper/` |
| **Priorytet modułu** | CORE (dane), formularz „Dodaj wydarzenie” — OPCJONALNY |
| **Korzysta z** | `shared/models.py` (`Event`, `Category`, `stable_id`, `normalize_tag`, `is_in_krakow`, `INTEREST_TAGS`), `shared/storage.py` (`upsert_events`), `shared/mock_data.py` (`KRAKOW_VENUES`) |
| **Dostarcza dla** | wszystkich: realne wydarzenia z Krakowa w bazie (`events`) |
| **Sandbox** | `streamlit run m2_scraper/sandbox.py` (podgląd bez zapisu) |
| **Testy** | `pytest m2_scraper` |
| **CLI** | `python -m m2_scraper.run --source <nazwa> [--dry-run]` |

---

## 1. Cel

Na demo mapa pokazuje **prawdziwe, aktualne** wydarzenia z Krakowa (min. 50 z poprawnymi współrzędnymi), a demo nie zależy od internetu ani od dostępności zewnętrznych stron.

## 2. Zakres

### 2.1 Stan wyjściowy (działa w szkielecie)

- Protokół `EventSource` (`name`, `fetch() -> list[Event]`) i `PoliteHttp` (User-Agent, opóźnienie, cache HTML na dysku).
- Źródła: `MockSource` (mocki) i `ManualJsonSource` (JSON → `Event`, z geokodowaniem brakujących współrzędnych).
- `geocode()` — słownik znanych miejsc Krakowa + odczyt cache; **Nominatim = TODO**.
- Pipeline `run.py`: fetch → odrzucenie eventów spoza Krakowa → `storage.upsert_events()` (idempotentne).
- Aplikacja widzi nowe dane **bez restartu** (Storage wykrywa zapis z innego procesu przez `PRAGMA data_version`).

### 2.2 Zadania atomowe

| ID | Zadanie | Prio | Est. | Gotowe gdy |
|----|---------|------|------|------------|
| M2-01 | Rozpoznanie źródeł: 2–3 kandydatów (np. kalendarz Karnet Krakowskiego Biura Festiwalowego, strony instytucji: Filharmonia, Opera, MOCAK, teatry). Sprawdź `robots.txt`, regulamin, czy treść jest w HTML (requests) czy JS (Playwright) | MUST | 1 h | Decyzja do H1.5: źródło główne + zapasowe, zapisana w README modułu |
| M2-02 | Źródło #1: `sources/<nazwa>.py` — lista eventów → strona szczegółów → surowe pola; `PoliteHttp` z cache (pracuj offline na zapisanym HTML) | MUST | 3 h | `--dry-run` zwraca ≥ 30 eventów |
| M2-03 | Normalizacja: kategoria źródła → `Category`, słowa kluczowe → tagi z `INTEREST_TAGS`, polskie daty („pt, 10 paź, 19:00”) → `datetime`, cena („wstęp wolny”, „od 40 zł”) → `price_pln` | MUST | 2 h | Testy parserów dat/cen na 10+ przykładach z fixture HTML |
| M2-04 | Geokodowanie: Nominatim (max 1 req/s, własny User-Agent, `countrycodes=pl`, `viewbox` Krakowa) + zapis do `data/cache/geocode.json`; najpierw `KRAKOW_VENUES` | MUST | 2 h | ≥ 90% eventów ma współrzędne; drugie uruchomienie nie robi zapytań sieciowych |
| M2-05 | Deduplikacja: `id = stable_id("ev", source, url)`; między źródłami heurystyka (`fold_text(title)`, data, miejsce) | MUST | 1 h | Dwukrotne uruchomienie nie dubluje pinezek |
| M2-06 | **Snapshot na demo**: `python -m m2_scraper.run --source <x> --export data/seed_events.json` → commit pliku; `ManualJsonSource(path)` ładuje go offline | MUST | 1 h | Na czystym klonie: reset + import snapshotu = pełna mapa bez internetu |
| M2-07 | Źródło #2 (zapasowe / uzupełniające kategorie, np. sport, meetupy) | SHOULD | 2 h | Łącznie ≥ 50 eventów w ≥ 5 kategoriach |
| M2-08 | Raport jakości w CLI: ile bez geo / ceny / opisu / tagów; flaga `--days N` (tylko najbliższe N dni) | SHOULD | 1 h | Raport drukuje się po każdym uruchomieniu |
| M2-09 | Formularz „Dodaj wydarzenie” (`add_event_form.py`): tytuł, kategoria, data/godzina, miejsce (geocode lub klik na mapie), tagi → `Event(source="user", created_by=user.id)`; potem `FEATURES["add_event"] = True` | COULD | 2 h | Dodany event od razu widoczny na mapie i w panelu |
| M2-10 | Obrazki (`image_url`) i linki do biletów (`url`) | COULD | 1 h | Panel M1 pokazuje link „Strona wydarzenia ↗” |

### 2.3 Poza zakresem

- Wyświetlanie eventów (M1), rekomendacje (M4).
- Harmonogram/cron scrapera — na demo wystarczy ręczne uruchomienie CLI + snapshot.

## 3. Kontrakty

### 3.1 Wejście (z `shared/`)

```python
from shared.models import Event, Category, stable_id, normalize_tag, fold_text, is_in_krakow, INTEREST_TAGS
from shared.storage import Storage, get_storage            # upsert_events(events) -> int
from shared.mock_data import KRAKOW_VENUES                  # znane miejsca: nazwa, adres, lat, lon
```

### 3.2 Wyjście — publiczne API

```python
# m2_scraper/base.py
class EventSource(Protocol):
    name: str
    def fetch(self) -> list[Event]: ...                      # NIE zapisuje do bazy

# m2_scraper/sources/__init__.py
SOURCES: dict[str, type[EventSource]]                       # rejestr źródeł dla CLI i sandboxa

# m2_scraper/geocode.py
geocode(venue: str, address: str = "") -> tuple[float, float] | None

# m2_scraper/run.py
collect(source: EventSource) -> list[Event]
run(source_names: list[str], storage: Storage | None = None, *, dry_run: bool = False) -> int

# m2_scraper/add_event_form.py   (OPCJONALNE, za flagą FEATURES["add_event"])
render_add_event_form(storage: Storage, user: User) -> None
```

**Wymagania na każdy `Event` z M2:** `source="scraper:<nazwa>"`, `id` deterministyczne, `lat/lon` w `KRAKOW_BBOX`, `start` naiwny czas lokalny, tagi z `INTEREST_TAGS` tam, gdzie się da (matching M4 działa na tagach!).

### 3.3 Stan sesji

Brak (moduł działa poza Streamlit). Formularz M2-09: tylko `state.go_to(View.MAP)` po zapisie; klucze prywatne `m2_*`.

### 3.4 Pliki modułu

`m2_scraper/**`, `data/seed_events.json`, `data/cache/**` (gitignore).

## 4. Niezależne testowanie (mocki)

1. **Fixture HTML**: zapisz 1–2 prawdziwe strony źródła do `m2_scraper/fixtures/` i testuj parser offline (`pytest m2_scraper`).
2. `python -m m2_scraper.run --source <x> --dry-run` — walidacja bez zapisu.
3. `streamlit run m2_scraper/sandbox.py` — tabela + mapa wyników przed zapisem do bazy.
4. Integracja: przy uruchomionym `app.py` odpal `python -m m2_scraper.run --source <x>` — po kliknięciu czegokolwiek w aplikacji pojawiają się nowe pinezki.

## 5. Definition of Done (demo)

- [ ] ≥ 50 prawdziwych eventów z Krakowa na mapie, ≥ 5 kategorii, ≥ 90% z tagami.
- [ ] `data/seed_events.json` w repo — demo działa offline.
- [ ] Ponowne uruchomienie nie tworzy duplikatów.
- [ ] Respektowane `robots.txt` i limit zapytań; cache HTML i geokodowania.
- [ ] `pytest` zielony (parsery dat/cen mają testy).

## 6. Ryzyka i plan B

| Ryzyko | Sygnał ostrzegawczy | Plan B |
|---|---|---|
| Strona blokuje / zmienia HTML / renderuje JS | 403, pusty wynik, brak danych w HTML | Źródło zapasowe; Playwright (`requirements.txt`, sekcja opcjonalna); ostatecznie **ręcznie zebrane 50 eventów w JSON** (`ManualJsonSource`) — to też „prawdziwe dane” |
| Regulamin zabrania scrapowania | Zapis w ToS/robots | Nie scrapujemy tego źródła; używamy publicznych stron instytucji / ręcznego JSON |
| Nominatim nie znajduje adresu | > 10% eventów bez geo | Rozszerz `KRAKOW_VENUES`; geokoduj po samej nazwie miejsca + „Kraków” |
| Brak internetu na demo | — | Snapshot `data/seed_events.json` + cache HTML |

## 7. Punkty synchronizacji

| Kiedy | Co musi być na `main` |
|---|---|
| H1.5 | Wybrane źródła (decyzja w README modułu) |
| H6 | Źródło #1 w `--dry-run` zwraca eventy; parsery z testami |
| H12 | Prawdziwe eventy w bazie + snapshot `data/seed_events.json` |
| H18 | Feature freeze: źródło #2 lub formularz (jeśli zdążone) |
