# TASK_SPEC — M4: Silnik matchingu i rekomendacji

| | |
|---|---|
| **Właściciel** | _Dev 4_ |
| **Folder** | `m4_matching/` |
| **Priorytet modułu** | CORE (matching na evencie), rekomendacje — OPCJONALNE (ale tanie) |
| **Korzysta z** | `shared/models.py` (`User`, `Event`, `Attendance`, `MatchResult`, `Recommendation`), `shared/storage.py` (`list_attendees`, `list_user_attendance`, `get_users`, `list_users`, `list_events`) |
| **Dostarcza dla** | M1 (lista „Pasujące osoby” w prawym panelu, „Polecane dla Ciebie”), M3 (osoby podobne do mnie — opcjonalnie), M5 (wspólne tagi → icebreakery) |
| **Sandbox** | `streamlit run m4_matching/sandbox.py` (strojenie wag na żywo) · `python -m m4_matching.engine` |
| **Testy** | `pytest m4_matching` |

---

## 1. Cel

Po kliknięciu wydarzenia użytkownik widzi osoby, które tam idą, **posortowane od najlepiej pasujących**, z krótkim, ludzkim uzasadnieniem („Oboje lubicie jazz i fotografię”).

## 2. Zakres

### 2.1 Stan wyjściowy (działa w szkielecie)

- `tag_similarity` — Jaccard po tagach + lista wspólnych tagów.
- `match_for_event` — uczestnicy eventu bez mnie i bez osób z `open_to_meet=False`, sortowanie po score.
- `recommend_events` — przyszłe eventy, na które nie jestem zapisany, ranking po pokryciu tagów.
- `widgets.render_recommendations` — „✨ Polecane dla Ciebie” w pustym prawym panelu.

### 2.2 Zadania atomowe

| ID | Zadanie | Prio | Est. | Gotowe gdy |
|----|---------|------|------|------------|
| M4-01 | Scoring v1: Jaccard ważony **IDF** (rzadki wspólny tag „opera” > popularny „kino”); wynik w [0, 1]; deterministyczny tie-break | MUST | 2 h | Testy: monotoniczność, zakres, deterministyczność |
| M4-02 | Dodatkowe sygnały: wspólne inne wydarzenia (co-attendance), dopasowanie osoby do tagów eventu, `GOING` > `INTERESTED`; wszystkie wagi w jednym słowniku `WEIGHTS` | MUST | 1.5 h | Zmiana wagi w `WEIGHTS` zmienia ranking w sandboxie |
| M4-03 | Uzasadnienia PL (≤ 60 znaków, poprawna odmiana): „Oboje lubicie jazz i fotografię”, „Byliście razem na 2 wydarzeniach”, „Idziecie na to samo wydarzenie” | MUST | 1 h | Każdy `MatchResult.reason` niepusty i czytelny |
| M4-04 | Testy „złotych przypadków” na mockach (np. dla `u_ola` na `e_jazz_alchemia` Bartek/Natalia wyżej niż Tomek) + wykluczenia (self, `open_to_meet=False`) | MUST | 1 h | `pytest m4_matching` zielony, ≥ 8 testów |
| M4-05 | Rekomendacje v2: tagi + „osoby podobne do Ciebie idą na…” (eventy top-matchy) + kara za odległy termin + różnorodność (max 2 z jednej kategorii w top 5) | SHOULD | 2 h | Rekomendacje dla 3 person demo są sensowne i różnorodne |
| M4-06 | `match_users(storage, user, *, limit)` — globalne dopasowania (`event_id=None`) do profilu/onboardingu | SHOULD | 1 h | Funkcja + testy; użyte przez M3 jeśli zdążą |
| M4-07 | Wydajność: benchmark 500 eventów × 200 osób; `match_for_event` < 20 ms, `recommend_events` < 50 ms; IDF liczone raz na wersję danych | SHOULD | 1 h | Benchmark w teście (`time.perf_counter`) przechodzi |
| M4-08 | Podobieństwo opisów (bio) — TF-IDF / embeddingi — tylko za flagą i tylko jeśli MUST gotowe | COULD | 2 h | Flaga w `WEIGHTS`/`FEATURES`, brak wpływu na czas reruna > 50 ms |
| M4-09 | Dopracowanie widgetu rekomendacji (`widgets.py`): mini-karty, „idzie N osób, w tym X pasujących” | COULD | 1 h | Widget wygląda spójnie z panelem M1 |

### 2.3 Poza zakresem

- Rysowanie kart osób (M3 — `render_user_card`), układ panelu (M1), zapisywanie się na eventy (M5).
- **`engine.py` nie importuje streamlit** — czysta logika, testowalna pytestem.

## 3. Kontrakty

### 3.1 Wejście (z `shared/`)

```python
from shared.models import User, Event, Attendance, AttendanceStatus, MatchResult, Recommendation
from shared.storage import Storage   # list_attendees(event_id), list_user_attendance(user_id), get_users(ids),
                                     # list_users(), list_events(criteria=None), get_event(id)
```

Wszystkie odczyty idą ze snapshotu w RAM (µs) — **nie trzeba** własnego cache dla danych, tylko ewentualnie dla obliczeń (IDF).

### 3.2 Wyjście — publiczne API

```python
# m4_matching/engine.py  (bez streamlit)
tag_similarity(a: list[str], b: list[str]) -> tuple[float, list[str]]
match_for_event(storage: Storage, user: User, event_id: str, *, limit: int = 10) -> list[MatchResult]
recommend_events(storage: Storage, user: User, *, limit: int = 5) -> list[Recommendation]
# nowe (SHOULD):
match_users(storage: Storage, user: User, *, limit: int = 10) -> list[MatchResult]

# m4_matching/widgets.py  (UI)
render_recommendations(storage: Storage, user: User, *, limit: int = 5) -> None
```

Gwarancje: `0 ≤ score ≤ 1`, lista posortowana malejąco, brak `user` na liście, brak osób z `open_to_meet=False`, `reason` niepusty.

### 3.3 Stan sesji

| Klucz / funkcja `shared.state` | Czyta | Pisze |
|---|---|---|
| `select_event()` | — | ✅ (klik „Pokaż” w rekomendacji) |

Prywatne: `m4_*`.

### 3.4 Pliki modułu

`m4_matching/**`.

## 4. Niezależne testowanie (mocki)

1. `python -m m4_matching.engine` — wypisuje dopasowania i rekomendacje dla `u_ola`.
2. `streamlit run m4_matching/sandbox.py` — wybór osoby i eventu, tabele dopasowań i rekomendacji; stroisz `WEIGHTS` i od razu widzisz efekt (`runOnSave`).
3. `pytest m4_matching` — fixture `storage` (mocki w RAM) i `demo_user` z `conftest.py`.
4. Własne scenariusze: `storage.upsert_user(...)`, `storage.join_event(...)` na `Storage(":memory:")`.

## 5. Definition of Done (demo)

- [ ] Dla każdego eventu z ≥ 2 uczestnikami lista dopasowań jest posortowana sensownie i ma uzasadnienia.
- [ ] Zmiana tagów w profilu (M3) zmienia ranking od razu.
- [ ] Rekomendacje nie zawierają eventów przeszłych ani tych, na które użytkownik już się zapisał.
- [ ] Czasy w normie (M4-07), `pytest` zielony.

## 6. Ryzyka i plan B

| Ryzyko | Sygnał ostrzegawczy | Plan B |
|---|---|---|
| Prawdziwe eventy (M2) mają słabe tagi → słabe dopasowania | Prawie wszystkie score ≈ 0 | Dopasowanie po tagach osób (Jaccard na profilach) dominuje; z M2 uzgodnij mapowanie słów kluczowych na `INTEREST_TAGS` |
| Za mało uczestników na prawdziwych eventach | Puste listy | Skrypt demo zapisuje persony na wybrane prawdziwe eventy (`storage.join_event`) |
| ML/embeddingi zjadają czas | M4-08 > 2 h | Porzucić — Jaccard+IDF z dobrymi uzasadnieniami wygrywa demo |

## 7. Punkty synchronizacji

| Kiedy | Co musi być na `main` |
|---|---|
| H1 | Kontrakt API potwierdzony z M1 |
| H6 | M4-01..M4-04 (scoring v1 + uzasadnienia + testy) |
| H12 | M4-05 / M4-06 |
| H18 | Feature freeze, wagi zamrożone |
