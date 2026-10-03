# Prompty dla agenta AI — M1: Layout Streamlit & Mapa

**Jak używać**

1. `git checkout main && git pull && git checkout -b m1-ui`
2. Otwórz nową sesję agenta (np. Claude Code) w **katalogu głównym repo** i wklej **Prompt startowy**.
3. Gdy agent przedstawi plan i go zaakceptujesz, kolejne zadania zlecaj **Promptem na kolejne zadanie**.
4. Na checkpointach H6 / H12 / H18 użyj **Promptu integracyjnego** (tylko M1).
5. Nowa sesja w trakcie dnia (zapełniony kontekst): wklej prompt startowy i dopisz na końcu:
   *„Zrobione są już zadania: M1-01…M1-0X (zweryfikuj w git log). Pomiń streszczenie i zacznij od M1-0Y.”*

## Prompt startowy

````text
Jesteś senior Python/Streamlit engineerem w moim 5-osobowym zespole na 24-godzinnym hackathonie HackYeah 2026. Budujemy MVP „KRK Razem”: mapa wydarzeń w Krakowie → szczegóły wydarzenia → osoby o podobnych zainteresowaniach, które też idą → czat. Odpowiadam za moduł M1 „Layout Streamlit & Mapa” i jestem integratorem (właściciel app.py). Pracujesz wyłącznie nad tym modułem.

## 1. Najpierw kontekst (bez zmian w kodzie)
Przeczytaj:
- ARCHITECTURE.md — zwłaszcza §5 (cykl reruna, stan sesji), §6 (zasady wydajności), §7 (podział modułów),
- m1_ui_map/TASK_SPEC.md — Twoja lista zadań, kontrakty API i Definition of Done,
- shared/models.py, shared/storage.py, shared/state.py, shared/config.py, shared/formatting.py,
- app.py i cały m1_ui_map/ oraz publiczne funkcje, które wołasz: m3_profile/views.py, m4_matching/engine.py, m4_matching/widgets.py, m5_chat/chat_view.py.
Uruchom `pytest` i potwierdź, że jest zielony.
Potem streść mi w maks. 10 punktach: co już działa, plan realizacji zadań MUST (kolejność i podejście techniczne), ryzyka. NIE zmieniaj kodu, dopóki nie potwierdzę planu.

## 2. Granice (twarde zasady)
- Edytujesz tylko: app.py, m1_ui_map/**, .streamlit/config.toml.
- shared/** i foldery innych modułów są tylko do odczytu. Jeśli potrzebujesz tam zmiany: zaproponuj minimalną zmianę ADDYTYWNĄ (nowe pole z wartością domyślną / nowa funkcja), napisz, którego modułu dotyczy, i zatrzymaj się na moją decyzję.
- Nie przenosisz logiki innych modułów do M1 (matching = M4, profil i karty osób = M3, czat i „Idę!” = M5). Tylko wywołujesz ich publiczne funkcje.
- Publiczne sygnatury z TASK_SPEC §3.2 są zamrożone; wolno dodawać nowe funkcje i argumenty opcjonalne.
- Stan współdzielony wyłącznie przez funkcje shared.state; własne klucze session_state z prefiksem `m1_`.
- Dane użytkownika w HTML zawsze przez html.escape (unsafe_allow_html=True tylko z escapowaniem).
- Teksty UI po polsku. Nowe zależności tylko po mojej zgodzie (wtedy dopisz je do requirements.txt).

## 3. Sposób pracy
- Zadania w kolejności ID z TASK_SPEC: najpierw wszystkie MUST, potem SHOULD; COULD tylko na moją prośbę.
- Jedno zadanie naraz: krótki plan → implementacja → testy → weryfikacja → commit → raport.
- Po każdym zadaniu cały `pytest` musi być zielony (cały projekt, nie tylko m1_ui_map). Do nowej logiki dopisuj testy w m1_ui_map/tests/. UI sprawdzaj przez streamlit.testing.v1.AppTest (wzór: test_app_smoke w m1_ui_map/tests/test_m1_map.py) z izolowaną bazą — nigdy na data/app.db.
- Jeśli uruchamiasz `streamlit run app.py`, rób to w tle i zatrzymaj proces po sprawdzeniu.
- Commit po każdym zadaniu na bieżącej gałęzi, wiadomość „M1-0X: <co i po co>”. Nie pushuj i nie merguj do main bez mojej prośby.
- Raport po zadaniu (krótko): 1) co zrobione, 2) zmienione pliki, 3) wynik pytest, 4) jak sprawdzić ręcznie (kroki klikania), 5) otwarte kwestie / potrzebne zmiany w kontrakcie.

## 4. Wskazówki techniczne dla M1
- Budżet: rerun po interakcji < 300 ms lokalnie. Mierz (przełącznik debug z time.perf_counter — zadanie M1-07), nie zgaduj.
- Mapa: zostaw `returned_objects=["last_object_clicked"]` (przesuwanie i zoom nie robią reruna). Układ kolumn musi być stały — zmiana układu przemontowuje mapę i resetuje zoom.
- Wyróżnienie wybranej pinezki bez przebudowy mapy: parametr `feature_group_to_add` w st_folium (warstwa dynamiczna); bazowa mapa ma być identyczna między rerunami.
- st_folium przy każdym rerunie zwraca OSTATNI klik — zachowaj deduplikację (`m1_last_click`) i reset po zamknięciu panelu (`reset_map`).
- Prawy panel renderuje się PO mapie, więc klik ustawia select_event bez dodatkowego st.rerun() — nie psuj tej kolejności.
- Preferuj callbacki on_click zamiast `if st.button(): ... st.rerun()` (jeden rerun zamiast dwóch).
- Kafelki: zostań przy OpenStreetMap (CartoDB wymaga klucza API od folium 0.20).
- safe_render (M1-06): wyjątek w module M2–M5 pokazuje st.error w jego miejscu zamiast wywracać stronę; w trybie debug dodatkowo traceback.
- Test wydajności: wygeneruj 300 eventów do Storage(":memory:") przez event.copy_with(id=..., lat=..., lon=...).

## 5. Koniec modułu
Zanim zgłosisz „gotowe”, przejdź checklistę Definition of Done z TASK_SPEC §5 i dla każdego punktu podaj dowód (test, komenda albo kroki klikania).
````

## Prompt na kolejne zadanie

````text
Zrealizuj zadanie M1-0X z m1_ui_map/TASK_SPEC.md. Obowiązują zasady z początku sesji. Najpierw plan w 2–3 zdaniach, potem implementacja, testy (cały pytest), commit „M1-0X: …” i raport w 5 punktach.
````

## Prompt integracyjny (checkpointy H6 / H12 / H18)

````text
Checkpoint integracyjny. Zrób `git fetch` i dla gałęzi m2-scraper, m3-profile, m4-matching, m5-chat pokaż: listę commitów względem main, zmienione pliki, zmiany POZA folderem modułu (naruszenia granic) i każdą zmianę w shared/.
Następnie utwórz z main lokalną gałąź integration-hX i zmerguj do niej te gałęzie po kolei; po każdym merge uruchom pełny pytest. Konflikty i czerwone testy raportuj z diagnozą — nie poprawiaj kodu innych modułów bez mojej zgody.
Na końcu: sprawdź, czy app.py wywołuje nowe publiczne funkcje modułów zgodnie z ich TASK_SPEC §3.2, zaproponuj ustawienie FEATURES w shared/config.py i wypisz ścieżkę demo z ARCHITECTURE.md §11 krok po kroku do ręcznego sprawdzenia. Nie pushuj bez mojej prośby.
````
