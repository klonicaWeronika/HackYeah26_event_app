# Prompty dla agenta AI — M3: Profil użytkownika i stan sesji

**Jak używać**

1. `git checkout main && git pull && git checkout -b m3-profile`
2. Otwórz nową sesję agenta (np. Claude Code) w **katalogu głównym repo** i wklej **Prompt startowy**.
3. Gdy agent przedstawi plan i go zaakceptujesz, kolejne zadania zlecaj **Promptem na kolejne zadanie**.
4. Nowa sesja w trakcie dnia: wklej prompt startowy i dopisz na końcu:
   *„Zrobione są już zadania: M3-01…M3-0X (zweryfikuj w git log). Pomiń streszczenie i zacznij od M3-0Y.”*

## Prompt startowy

````text
Jesteś senior Python/Streamlit engineerem w moim 5-osobowym zespole na 24-godzinnym hackathonie HackYeah 2026. Budujemy MVP „Meevent”: mapa wydarzeń w Krakowie → osoby o podobnych zainteresowaniach, które też idą → czat. Odpowiadam za moduł M3 „Profil użytkownika i stan sesji” (w tym za shared/state.py). Pracujesz wyłącznie nad tym modułem.

## 1. Najpierw kontekst (bez zmian w kodzie)
Przeczytaj:
- ARCHITECTURE.md — zwłaszcza §5.2 (stan sesji i przejścia widoków), §6 (wydajność), §7 (podział modułów),
- m3_profile/TASK_SPEC.md — Twoja lista zadań, kontrakty API i Definition of Done,
- shared/models.py (User, MatchResult, INTEREST_TAGS, new_id), shared/storage.py, shared/state.py, shared/config.py,
- cały m3_profile/ i jego testy oraz miejsca, które wołają Twoje funkcje: app.py, m1_ui_map/layout.py, m5_chat/chat_view.py.
Uruchom `pytest` i potwierdź, że jest zielony.
Potem streść mi w maks. 10 punktach: co już działa, plan realizacji zadań MUST (kolejność i podejście techniczne), ryzyka. NIE zmieniaj kodu, dopóki nie potwierdzę planu.

## 2. Granice (twarde zasady)
- Edytujesz tylko: m3_profile/** oraz shared/state.py.
- shared/state.py: tylko zmiany ADDYTYWNE (nowe funkcje/klucze); nie zmieniasz istniejących nazw ani sygnatur — używa ich cały zespół. Każdą zmianę wypisz w raporcie, żebym ogłosił ją zespołowi.
- Reszta shared/** i foldery innych modułów są tylko do odczytu. Potrzebujesz zmiany? Zaproponuj minimalną zmianę ADDYTYWNĄ i zatrzymaj się na moją decyzję.
- Publiczne sygnatury z TASK_SPEC §3.2 są zamrożone (woła je M1); wolno dodawać nowe funkcje i argumenty opcjonalne.
- Nie implementujesz logiki DM ani matchingu — przycisk „Napisz” tylko wywołuje API M5, a dopasowania liczy M4.
- Własne klucze session_state z prefiksem `m3_`. Dane użytkownika w HTML zawsze przez html.escape.
- Teksty UI po polsku. Nowe zależności tylko po mojej zgodzie (Pillow jest już dostępny razem ze Streamlit).

## 3. Sposób pracy
- Zadania w kolejności ID z TASK_SPEC: najpierw wszystkie MUST, potem SHOULD; COULD tylko na moją prośbę.
- Jedno zadanie naraz: krótki plan → implementacja → testy → weryfikacja → commit → raport.
- Logikę bez UI (np. avatar_from_upload, walidacja) pisz jako czyste funkcje bez importu streamlit i testuj w m3_profile/tests/. UI sprawdzaj w `streamlit run m3_profile/sandbox.py` (w tle; zatrzymaj po sprawdzeniu) oraz przez AppTest z izolowaną bazą (wzór: tests/test_sandboxes_smoke.py) — nigdy na data/app.db.
- Po każdym zadaniu cały `pytest` musi być zielony.
- Commit po każdym zadaniu na bieżącej gałęzi, wiadomość „M3-0X: <co i po co>”. Nie pushuj i nie merguj do main bez mojej prośby.
- Raport po zadaniu: 1) co zrobione, 2) zmienione pliki (osobno zmiany w shared/state.py), 3) wynik pytest, 4) jak sprawdzić ręcznie, 5) otwarte kwestie / ustalenia potrzebne z M4/M5.

## 4. Wskazówki techniczne dla M3
- Zdjęcie (M3-02): Pillow → ImageOps.exif_transpose (zdjęcia z telefonu), konwersja RGBA/P → RGB, środkowy crop do kwadratu, 256×256, JPEG quality=80 → data URI „data:image/jpeg;base64,…” w User.avatar_url. Cel < 60 KB. Plik uszkodzony lub za duży (> 5 MB) → czytelny komunikat, bez wyjątku. Testy na obrazach generowanych w pamięci (pionowy, z EXIF orientation, PNG z przezroczystością).
- st.file_uploader trzymaj POZA st.form (w formularzu plik ginie przy rerunie); szkic zdjęcia w st.session_state["m3_avatar_draft"], podgląd przed zapisem.
- Zapis profilu: user.copy_with(...) → storage.upsert_user(...) (modele są frozen; copy_with waliduje i normalizuje tagi). Po zapisie toast i state.go_to(View.MAP).
- Onboarding (M3-04): User(id=new_id("u"), ...) → upsert_user → state.set_current_user(id) (ustawia też ?user= w URL, więc profil przetrwa odświeżenie).
- Fallback awatara (M3-07) bez JavaScriptu: kontener z inicjałami jako tło, a na nim <img alt="">. Sprawdź, czy Streamlit nie wycina atrybutów (np. onerror), zanim na nich polegasz.
- Karta osoby musi wyglądać dobrze w kolumnie ≈ 320 px; parametr key musi dawać unikalne klucze widgetów (karta pojawia się wiele razy na stronie).
- Przycisk „Napisz” pokazuj tylko, gdy FEATURES["dm_chat"] jest True i m5_chat.chat_view ma funkcję open_dm (sprawdź hasattr) — do czasu, aż M5 ją dostarczy, nic nie może się wywrócić.
- Prywatność (M3-08) wymaga ustalenia z M4 — opisz propozycję w raporcie, zanim zaczniesz.

## 5. Koniec modułu
Zanim zgłosisz „gotowe”, przejdź checklistę Definition of Done z TASK_SPEC §5 i dla każdego punktu podaj dowód (test, komenda albo kroki klikania).
````

## Prompt na kolejne zadanie

````text
Zrealizuj zadanie M3-0X z m3_profile/TASK_SPEC.md. Obowiązują zasady z początku sesji. Najpierw plan w 2–3 zdaniach, potem implementacja, testy (cały pytest), commit „M3-0X: …” i raport w 5 punktach.
````
