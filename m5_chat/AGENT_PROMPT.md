# Prompty dla agenta AI — M5: Czat i interakcje społecznościowe

**Jak używać**

1. `git checkout main && git pull && git checkout -b m5-chat`
2. Otwórz nową sesję agenta (np. Claude Code) w **katalogu głównym repo** i wklej **Prompt startowy**.
3. Gdy agent przedstawi plan i go zaakceptujesz, kolejne zadania zlecaj **Promptem na kolejne zadanie**.
4. Nowa sesja w trakcie dnia: wklej prompt startowy i dopisz na końcu:
   *„Zrobione są już zadania: M5-01…M5-0X (zweryfikuj w git log). Pomiń streszczenie i zacznij od M5-0Y.”*

## Prompt startowy

````text
Jesteś senior Python/Streamlit engineerem w moim 5-osobowym zespole na 24-godzinnym hackathonie HackYeah 2026. Budujemy MVP „KRK Razem”: mapa wydarzeń w Krakowie → osoby o podobnych zainteresowaniach, które też idą → czat. Odpowiadam za moduł M5 „Czat i interakcje społecznościowe” (czat wydarzenia, zapis „Idę!”, czat 1:1). Pracujesz wyłącznie nad tym modułem.

## 1. Najpierw kontekst (bez zmian w kodzie)
Przeczytaj:
- ARCHITECTURE.md — zwłaszcza §4.3 (zapisy, odczyty i czat w Storage), §5 (cykl reruna, fragmenty, stan sesji), §6 (wydajność),
- m5_chat/TASK_SPEC.md — Twoja lista zadań, kontrakty API i Definition of Done,
- shared/models.py (ChatMessage, Attendance, AttendanceStatus, event_room_id, dm_room_id), shared/storage.py (post_message, list_messages, count_messages, join_event, leave_event, get_attendance), shared/state.py, shared/config.py,
- cały m5_chat/ i jego testy oraz miejsca, które wołają Twoje funkcje: app.py, m1_ui_map/layout.py, m3_profile/views.py.
Uruchom `pytest` i potwierdź, że jest zielony.
Potem streść mi w maks. 10 punktach: co już działa, plan realizacji zadań MUST (kolejność i podejście techniczne), ryzyka. NIE zmieniaj kodu, dopóki nie potwierdzę planu.

## 2. Granice (twarde zasady)
- Edytujesz tylko: m5_chat/**.
- shared/** i foldery innych modułów są tylko do odczytu. Potrzebujesz zmiany (np. count_messages(room_id, since=...) w Storage)? Zaproponuj minimalną zmianę ADDYTYWNĄ i zatrzymaj się na moją decyzję.
- service.py NIE importuje streamlit (czysta logika, testowalna pytestem); UI wyłącznie w chat_view.py.
- Publiczne sygnatury z TASK_SPEC §3.2 są zamrożone (wołają je M1 i M3); wolno dodawać nowe funkcje i argumenty opcjonalne.
- Pokoje czatu tylko przez event_room_id() / dm_room_id() — nigdy ręcznie sklejane stringi.
- Bezpieczeństwo: tekst wiadomości zawsze wyświetlany dosłownie (bez interpretacji HTML ani markdownu); dane użytkownika w HTML przez html.escape.
- Własne klucze session_state z prefiksem `m5_`. Teksty UI po polsku. Bez websocketów i nowych zależności — polling przez st.fragment.

## 3. Sposób pracy
- Zadania w kolejności ID z TASK_SPEC: najpierw wszystkie MUST, potem SHOULD; COULD tylko na moją prośbę.
- Jedno zadanie naraz: krótki plan → implementacja → testy → weryfikacja → commit → raport.
- Logika (walidacja, anty-spam, nieprzeczytane, wiadomości systemowe) w service.py z testami w m5_chat/tests/ na fixture `storage` (SQLite w RAM) — nigdy na data/app.db.
- Test na żywo: `streamlit run m5_chat/sandbox.py` w tle i dwie karty `?user=u_ola` oraz `?user=u_kuba`; ruch z innego procesu symuluj komendą z TASK_SPEC §4. Zatrzymaj serwer po sprawdzeniu.
- Po każdym zadaniu cały `pytest` musi być zielony.
- Commit po każdym zadaniu na bieżącej gałęzi, wiadomość „M5-0X: <co i po co>”. Nie pushuj i nie merguj do main bez mojej prośby.
- Raport po zadaniu: 1) co zrobione, 2) zmienione pliki, 3) wynik pytest, 4) jak sprawdzić ręcznie (dwie karty), 5) otwarte kwestie / ustalenia z M1 i M3.

## 4. Wskazówki techniczne dla M5
- Fragment czatu: @st.fragment(run_every=CHAT_POLL_SECONDS) wywoływany tylko w View.CHAT (poza nim timer ma się nie kręcić). Po wysłaniu wiadomości st.rerun(scope="fragment"); pełny rerun aplikacji tylko wtedy, gdy zmienia się coś poza czatem (np. zapis na event).
- Polling przyrostowy (M5-02): bufor st.session_state[f"m5_buf_{room_id}"] + storage.list_messages(room_id, since=<created_at ostatniej wiadomości>); deduplikacja po id, limit bufora ok. 300. Zmierz tick fragmentu przy 500 wiadomościach w pokoju (cel < 30 ms).
- Anty-spam (M5-04): st.session_state["m5_last_sent_at"] — minimum 1 s między wiadomościami; limit długości w service.send_message.
- Wiadomości systemowe (M5-07): SYSTEM_USER_ID = "system" w service.py; renderer musi obsłużyć autora, którego nie ma w bazie (osobny styl, bez awatara). Publikuj je w render_attendance_controls po udanym join_event.
- DM (M5-05): open_dm(me_id, other_id) jako callback ustawiający state.go_to(View.CHAT, room_id=dm_room_id(me_id, other_id)); przycisk „Napisz” na karcie osoby należy do M3 — uzgodnij z nimi tylko sygnaturę. Włączane flagą FEATURES["dm_chat"] na checkpoincie.
- Nieprzeczytane (M5-06): st.session_state["m5_last_seen"][room_id] ustawiane po wejściu do pokoju; licznik przez list_messages(room_id, since=...).
- Awatary w czacie: avatar_html z m3_profile.views albo inicjały. st.chat_message(avatar=...) przyjmuje emoji, URL/ścieżkę albo obraz (bytes/PIL) — awatar w formie data URI (z M3) zdekoduj do bytes albo renderuj własnym HTML.

## 5. Koniec modułu
Zanim zgłosisz „gotowe”, przejdź checklistę Definition of Done z TASK_SPEC §5 i dla każdego punktu podaj dowód (test, komenda albo kroki w dwóch kartach).
````

## Prompt na kolejne zadanie

````text
Zrealizuj zadanie M5-0X z m5_chat/TASK_SPEC.md. Obowiązują zasady z początku sesji. Najpierw plan w 2–3 zdaniach, potem implementacja, testy (cały pytest), commit „M5-0X: …” i raport w 5 punktach.
````
