# TASK_SPEC — M3: Profil użytkownika i stan sesji

| | |
|---|---|
| **Właściciel** | _Dev 3_ (właściciel także `shared/state.py`) |
| **Folder** | `m3_profile/` + `shared/state.py` |
| **Priorytet modułu** | CORE |
| **Korzysta z** | `shared/models.py` (`User`, `MatchResult`, `INTEREST_TAGS`, `new_id`), `shared/storage.py` (`get_user`, `list_users`, `upsert_user`, `known_tags`, `list_user_attendance`), `shared/state.py` |
| **Dostarcza dla** | M1 (awatar w headerze, przełącznik użytkownika, widoki profilu), M1/M4 (karta osoby w liście dopasowań), M5 (awatary w czacie — `avatar_html`) |
| **Sandbox** | `streamlit run m3_profile/sandbox.py` |
| **Testy** | `pytest m3_profile` |

---

## 1. Cel

Każdy w 30 sekund tworzy profil (zdjęcie, zainteresowania, krótki opis), a karty osób w dopasowaniach wyglądają na tyle zachęcająco, że chce się napisać.

## 2. Zakres

### 2.1 Stan wyjściowy (działa w szkielecie)

- `avatar_html` / `render_avatar` — zdjęcie albo kolorowe inicjały, HTML escapowany.
- `render_user_switcher` — „Zaloguj jako…” (brak haseł w MVP), synchronizacja z `?user=` w URL.
- `render_user_card` — karta osoby z wynikiem dopasowania i uzasadnieniem.
- `render_profile_editor` — formularz: imię, bio (≤ 280), tagi (z możliwością dopisania własnych), URL zdjęcia.
- `render_profile_view` — podgląd cudzego profilu + lista wydarzeń, na które się wybiera.
- `shared/state.py` — kontrakt kluczy sesji (`View`, `go_to`, `select_event`, …).

### 2.2 Zadania atomowe

| ID | Zadanie | Prio | Est. | Gotowe gdy |
|----|---------|------|------|------------|
| M3-01 | Review `shared/state.py` z zespołem w H0–H1 (klucze, `View`) — od tej chwili jedyna droga do stanu współdzielonego | MUST | 0.5 h | Wszyscy znają `state.*`; nikt nie używa „gołych” kluczy współdzielonych |
| M3-02 | Upload zdjęcia: `st.file_uploader` (jpg/png/webp, ≤ 5 MB) → Pillow: `ImageOps.exif_transpose`, crop do kwadratu, 256×256, JPEG q=80 → **data URI** w `avatar_url`; czysta funkcja `avatar_from_upload(bytes) -> str` | MUST | 2 h | Zdjęcie z telefonu (pionowe, z EXIF) wyświetla się poprawnie w headerze, karcie i czacie; data URI < 60 KB |
| M3-03 | Walidacja edycji: imię 1–60, bio ≤ 280, 3–10 tagów, normalizacja; komunikaty przy polach; po zapisie toast + powrót do mapy | MUST | 1.5 h | Nie da się zapisać profilu łamiącego reguły; błędy są zrozumiałe |
| M3-04 | Onboarding: „Utwórz profil” (nowy `User(id=new_id("u"))`) — ekran powitalny dla nowej osoby, ustawienie `?user=` (profil przetrwa odświeżenie strony) | MUST | 2 h | Nowa osoba w 30 s ma profil i widzi dopasowania po zapisaniu się na event |
| M3-05 | Karta osoby: wynik jako badge/pasek, wspólne tagi wyróżnione, akcje „Profil” i „Napisz” (woła API M5, gdy `FEATURES["dm_chat"]`) | MUST | 1.5 h | Karta czytelna w wąskim prawym panelu (≈ 320 px) |
| M3-06 | Podgląd profilu: wspólne zainteresowania i wspólne wydarzenia z zalogowaną osobą, tylko przyszłe eventy, przycisk „Napisz” | SHOULD | 2 h | Z karty w panelu → profil → powrót do mapy z zachowanym wybranym eventem |
| M3-07 | Odporność awatarów: `onerror` w `<img>` → inicjały (brak internetu / zły URL) | SHOULD | 0.5 h | Zły URL nie pokazuje „zepsutego obrazka” |
| M3-08 | Prywatność: domyślne `open_to_meet` w profilu, możliwość ukrycia się we wszystkich dopasowaniach | COULD | 1.5 h | Ukryta osoba nie pojawia się w `match_for_event` (uzgodnij z M4) |
| M3-09 | „Persony demo” — w przełączniku opis scenariusza (np. „Ola — nowa w mieście, lubi jazz”) | COULD | 0.5 h | Prowadzący demo przełącza persony bez zastanowienia |

### 2.3 Poza zakresem

- Liczenie dopasowań (M4), czat/DM (M5), układ strony (M1).
- Prawdziwe logowanie/hasła/OAuth — świadomie poza MVP.

## 3. Kontrakty

### 3.1 Wejście (z `shared/`)

```python
from shared.models import User, MatchResult, INTEREST_TAGS, new_id, normalize_tag
from shared.storage import Storage      # get_user, get_users, list_users, upsert_user, known_tags, list_user_attendance, get_event
from shared import state                # current_user_id, set_current_user, go_to, viewed_user_id, select_event
from shared.config import FEATURES
```

### 3.2 Wyjście — publiczne API

```python
# m3_profile/views.py
avatar_html(user: User, size: int = 40) -> str                         # bezpieczny HTML (escapowany)
render_avatar(user: User, size: int = 40, caption: str | None = None) -> None
render_user_switcher(storage: Storage, key: str = "m3_user_switch") -> None
render_user_card(user: User, match: MatchResult | None = None, *, key: str) -> None
render_profile_editor(storage: Storage, user: User) -> None
render_profile_view(storage: Storage, user: User) -> None
# nowe (MUST):
avatar_from_upload(data: bytes) -> str                                 # data URI, bez streamlit
render_onboarding(storage: Storage) -> User | None
```

`shared/state.py` (właściciel M3) — zmiany tylko addytywne:

```python
init(default_user_id) · current_user_id() · set_current_user(id)
current_view() · go_to(view, *, room_id=None, user_id=None)
selected_event_id() · select_event(id | None)
get_filters() · set_filters(criteria) · chat_room_id() · viewed_user_id()
```

### 3.3 Stan sesji

| Klucz / funkcja `shared.state` | Czyta | Pisze |
|---|---|---|
| `current_user_id()` / `set_current_user()` | ✅ | ✅ (przełącznik, onboarding) |
| `go_to(View.PROFILE_*)`, `viewed_user_id()` | ✅ | ✅ |
| `select_event()` | — | ✅ (`None` po zmianie użytkownika) |

Prywatne: `m3_*` (formularz, przełącznik).

### 3.4 Pliki modułu

`m3_profile/**`, `shared/state.py`.

## 4. Niezależne testowanie (mocki)

1. `streamlit run m3_profile/sandbox.py` — zakładki: edycja, wszystkie karty osób, podgląd profilu; w sidebarze podgląd `session_state`.
2. `pytest m3_profile` — escapowanie HTML, fallback inicjałów, zapis profilu; dodaj: `avatar_from_upload` (pionowe zdjęcie z EXIF → kwadrat 256 px), walidacja.
3. Integracja: `streamlit run app.py` → ⚙️ Opcje → Edytuj profil → zmień tagi → wybierz event → dopasowania się zmieniają.

## 5. Definition of Done (demo)

- [ ] Nowa osoba tworzy profil ze zdjęciem z telefonu/laptopa w ≤ 30 s.
- [ ] Edycja tagów natychmiast wpływa na dopasowania (M4) bez restartu.
- [ ] Karty osób czytelne w prawym panelu; awatary nigdy „zepsute”.
- [ ] Odświeżenie strony nie wylogowuje (`?user=` w URL).
- [ ] `pytest` zielony.

## 6. Ryzyka i plan B

| Ryzyko | Sygnał ostrzegawczy | Plan B |
|---|---|---|
| Duże zdjęcia spowalniają reruny (data URI w każdym HTML) | Header/karty laggują | Twardy limit 256 px / q=80; ewentualnie pliki w `data/avatars/` + serwowanie przez `st.image` |
| `st.file_uploader` w `st.form` gubi plik po rerunie | Zdjęcie znika przed zapisem | Uploader poza formą, wynik w `st.session_state["m3_avatar_draft"]` |
| Zewnętrzne awatary (pravatar.cc) niedostępne | Brak zdjęć w mockach | M3-07: fallback do inicjałów |

## 7. Punkty synchronizacji

| Kiedy | Co musi być na `main` |
|---|---|
| H1 | `shared/state.py` zaakceptowany przez zespół |
| H6 | M3-02..M3-04: upload, walidacja, onboarding |
| H12 | M3-05/M3-06: karty i podgląd profilu (z akcją „Napisz” uzgodnioną z M5) |
| H18 | Feature freeze |
