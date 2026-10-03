# TASK_SPEC — M5: Czat i interakcje społecznościowe

| | |
|---|---|
| **Właściciel** | _Dev 5_ |
| **Folder** | `m5_chat/` |
| **Priorytet modułu** | „Idę!” — CORE (zasila matching) · czat wydarzenia — OPCJONALNY w specyfikacji, ale **kluczowy na demo** · DM — OPCJONALNY |
| **Korzysta z** | `shared/models.py` (`ChatMessage`, `Attendance`, `AttendanceStatus`, `event_room_id`, `dm_room_id`), `shared/storage.py` (`post_message`, `list_messages`, `count_messages`, `join_event`, `leave_event`, `get_attendance`) |
| **Dostarcza dla** | M1 (widok czatu w centrum, przyciski zapisu w panelu), M3 (akcja „Napisz” na karcie osoby) |
| **Sandbox** | `streamlit run m5_chat/sandbox.py` + dwie karty `?user=u_ola` / `?user=u_kuba` |
| **Testy** | `pytest m5_chat` |

---

## 1. Cel

Osoby idące na to samo wydarzenie mogą się umówić: zapisują się jednym kliknięciem („Idę!”) i rozmawiają w czacie wydarzenia na żywo — bez przeładowywania mapy.

## 2. Zakres

### 2.1 Stan wyjściowy (działa w szkielecie)

- `render_chat_room` — widok czatu w centrum; `@st.fragment(run_every=CHAT_POLL_SECONDS)` odświeża **tylko okno czatu**; `st.chat_input` w fragmencie.
- Wiadomości z innych kart/procesów pojawiają się po ≤ 2 s (wspólna baza SQLite).
- `render_attendance_controls` — „🙋 Idę!” / „Rezygnuję” + przełącznik „Pokaż mnie innym w dopasowaniach”.
- `service.send_message` (trim, odrzucenie pustych, limit 500 znaków), `service.room_title`.

### 2.2 Zadania atomowe

| ID | Zadanie | Prio | Est. | Gotowe gdy |
|----|---------|------|------|------------|
| M5-01 | UI czatu: własne vs cudze wiadomości (wyrównanie/kolor), awatary (`avatar_html` z M3 albo inicjały, gdy brak URL), grupowanie kolejnych wiadomości autora, pusty stan | MUST | 2 h | Rozmowa 3 osób jest czytelna na zrzucie ekranu |
| M5-02 | Wydajny polling: bufor `m5_buf_<room>` w `session_state` + `list_messages(room, since=ostatni_ts)` zamiast pobierania 150 wiadomości co 2 s | MUST | 1.5 h | Przy 500 wiadomościach w pokoju tick fragmentu < 30 ms, brak migotania |
| M5-03 | Zapis na event: status `GOING`/`INTERESTED` (`st.segmented_control`), `open_to_meet`, liczba zapisanych aktualizuje się w panelu | MUST | 1 h | Po kliknięciu „Idę!” osoba od razu pojawia się w dopasowaniach u innych |
| M5-04 | Bezpieczeństwo/anty-spam: tekst renderowany jako tekst (bez HTML/markdown injection), limit 1 wiadomość/s na sesję, przycięcie długości | MUST | 1 h | Wiadomość `<b>x</b>` i `**x**` wyświetla się dosłownie; flood blokowany komunikatem |
| M5-05 | DM 1:1: `open_dm(me_id, other_id)` → `state.go_to(View.CHAT, room_id=dm_room_id(...))`; przycisk „Napisz” na karcie M3; lista moich rozmów | SHOULD | 2 h | Z panelu dopasowań → „Napisz” → prywatny czat; włączone `FEATURES["dm_chat"]` |
| M5-06 | Nieprzeczytane: `last_seen[room_id]` w `session_state` → licznik na przycisku „💬 Czat wydarzenia (3 nowe)” | SHOULD | 1 h | Licznik rośnie, gdy ktoś pisze, i zeruje się po wejściu do czatu |
| M5-07 | Wiadomości systemowe: „Kuba dołączył do wydarzenia 🎉” przy `join_event` (`user_id="system"`, osobny styl) | SHOULD | 1 h | Dołączenie widoczne w czacie wydarzenia |
| M5-08 | Przypięta wiadomość organizacyjna („Spotykamy się 19:45 przy wejściu”) / reakcje emoji | COULD | 1.5 h | Przypięta wiadomość widoczna nad listą |
| M5-09 | Icebreakery: podpowiedzi pierwszej wiadomości z `MatchResult.shared_tags` (M4) | COULD | 1 h | Pusty DM pokazuje 3 klikalne propozycje |
| M5-10 | **Grupy na wydarzenia („ekipy”)** zamiast publicznego czatu wydarzenia: „Napisz” na pasującej osobie i lista „Idą / Interesuje ich” = zaproszenie do mojej grupy; zaproszona osoba dołącza albo odrzuca; każde kolejne zaproszenie zatwierdza cała grupa (głosowanie na czacie); 1 grupa na wydarzenie; nazwa wydarzenia i rząd awatarów nad czatem; „Opuść”; skrzynka „Ekipy” + toasty | SHOULD (mockup) | 4 h | Ola zaprasza Kubę → Kuba (druga karta) dołącza → Ola zaprasza Tomka → Kuba głosuje „Za” → Tomek dostaje zaproszenie |

### 2.3 Poza zakresem

- Websockety / push — świadomie polling przez `st.fragment(run_every=...)` (zero infrastruktury, działa w Streamlit).
- Liczenie dopasowań (M4), układ panelu (M1), karty osób (M3).

## 3. Kontrakty

### 3.1 Wejście (z `shared/`)

```python
from shared.models import ChatMessage, Event, User, Attendance, AttendanceStatus, event_room_id, dm_room_id
from shared.storage import Storage   # post_message, add_message, list_messages(room, since=, limit=), count_messages,
                                     # join_event, leave_event, get_attendance, list_attendees, get_users
from shared import state             # go_to(View.CHAT, room_id=...), chat_room_id(), current_user_id()
from shared.config import CHAT_POLL_SECONDS, FEATURES
```

Konwencja pokojów: `group:<group_id>` (czat grupy, M5-10) i `dm:<user_a>:<user_b>` (posortowane) — **tylko** przez `group_room_id()` / `dm_room_id()`. `event:<event_id>` zostaje w kontrakcie, ale UI go już nie otwiera.

### 3.2 Wyjście — publiczne API

```python
# m5_chat/service.py  (bez streamlit)
send_message(storage: Storage, room_id: str, user_id: str, text: str) -> ChatMessage | None
room_title(storage: Storage, room_id: str) -> str
# nowe (SHOULD):
unread_count(storage: Storage, room_id: str, since: datetime | None) -> int
SYSTEM_USER_ID = "system"

# m5_chat/chat_view.py  (UI)
render_chat_room(storage: Storage, user: User, room_id: str, *, height: int = 520) -> None
render_attendance_controls(storage: Storage, event: Event, user: User) -> None
# nowe (SHOULD):
open_dm(me_id: str, other_id: str) -> None          # callback dla „Napisz” w profilu (M3) — DM

# M5-10 grupy na wydarzenia
# m5_chat/groups.py (logika, bez streamlit): invite, vote, accept_invite, decline_invite, leave_group,
#     member_group, received_invites, votes_awaiting, invite_candidates, role_in
# m5_chat/group_view.py (UI):
open_event_chat(me_id, other_id, event_id) -> None                    # „Napisz” na karcie pasującej osoby (M3)
render_event_group_entry(storage, event_id, user) -> None             # sekcja ekipy w panelu wydarzenia (M1)
# m5_chat/inbox.py (UI):
render_inbox(storage, user) -> None                                   # skrzynka „Ekipy” w górnym pasku (M1)
render_group_notifier(storage, user) -> None                          # toasty o zaproszeniach z innych kart (app.py)
```

### 3.3 Stan sesji

| Klucz / funkcja `shared.state` | Czyta | Pisze |
|---|---|---|
| `chat_room_id()` | ✅ | — |
| `go_to(View.CHAT, room_id=…)` / `go_to(View.MAP)` | — | ✅ |
| `current_user_id()` | ✅ | — |

Prywatne: `m5_input_<room>`, `m5_buf_<room>`, `m5_last_seen`, `m5_last_sent_at`.

### 3.4 Pliki modułu

`m5_chat/**`.

## 4. Niezależne testowanie (mocki)

1. `streamlit run m5_chat/sandbox.py` i dwie karty: `http://localhost:8501/?user=u_ola`, `http://localhost:8501/?user=u_kuba` — pisz z obu.
2. Symulacja ruchu z innego procesu (jak drugi użytkownik):
   ```bash
   python -c "from shared.storage import get_storage; get_storage().post_message('event:e_jazz_alchemia', 'u_bartek', 'test z konsoli')"
   ```
3. `pytest m5_chat` — trim/odrzucenie pustych, limit długości, tytuły pokojów; dodaj: `since`, nieprzeczytane, anty-spam.
4. Grupy z wiadomościami w mockach: `g_jazz` (Kuba, Bartek, Natalia; Ola ma zaproszenie), `g_planszowki`, `g_fotospacer`.
   Stara baza `data/app.db` nie ma grup — `python -m shared.storage --reset`.

## 5. Definition of Done (demo)

- [ ] Dwie osoby w dwóch kartach rozmawiają na żywo (≤ 2 s opóźnienia), mapa się nie przeładowuje.
- [ ] „Idę!” natychmiast wpływa na dopasowania u innych osób.
- [ ] Brak możliwości wstrzyknięcia HTML w czacie; flood zablokowany.
- [ ] `pytest` zielony.

## 6. Ryzyka i plan B

| Ryzyko | Sygnał ostrzegawczy | Plan B |
|---|---|---|
| `run_every` obciąża serwer przy wielu kartach | CPU rośnie, czat laguje | `CHAT_POLL_SECONDS = 3–5`; bufor + `since` (M5-02) |
| `st.chat_input` w fragmencie zachowuje się nieintuicyjnie (np. pozycja) | Pole wpisywania skacze | `st.form` + `st.text_input` + `form_submit_button` w fragmencie |
| Fragment nie zatrzymuje się po wyjściu z czatu | Reruny w tle na mapie | Fragment wywoływany tylko w `View.CHAT` (już tak jest) — pilnować przy zmianach |

## 7. Punkty synchronizacji

| Kiedy | Co musi być na `main` |
|---|---|
| H1 | Kontrakt pokojów i API potwierdzony z M1/M3 |
| H6 | M5-01..M5-04 |
| H12 | M5-05 (DM) uzgodnione z M3 (przycisk „Napisz”), M5-06 |
| H18 | Feature freeze, `FEATURES["dm_chat"]` ustawione |
