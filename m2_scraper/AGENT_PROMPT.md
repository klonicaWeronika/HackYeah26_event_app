# Prompty dla agenta AI — M2: Scraper eventów i zasilanie bazy

**Jak używać**

1. `git checkout main && git pull && git checkout -b m2-scraper`
2. Otwórz nową sesję agenta (np. Claude Code) w **katalogu głównym repo** i wklej **Prompt startowy**.
3. Agent najpierw zrobi rozpoznanie źródeł (M2-01) i **poczeka na Twoją decyzję**, które źródło scrapować.
4. Kolejne zadania zlecaj **Promptem na kolejne zadanie**.
5. Nowa sesja w trakcie dnia: wklej prompt startowy i dopisz na końcu:
   *„Zrobione są już zadania: M2-01…M2-0X (zweryfikuj w git log). Wybrane źródło: <nazwa>. Pomiń streszczenie i zacznij od M2-0Y.”*

## Prompt startowy

````text
Jesteś senior Python engineerem (web scraping, przetwarzanie danych) w moim 5-osobowym zespole na 24-godzinnym hackathonie HackYeah 2026. Budujemy MVP „KRK Razem”: mapa wydarzeń w Krakowie → osoby o podobnych zainteresowaniach, które też idą → czat. Odpowiadam za moduł M2 „Scraper eventów i zasilanie bazy”. Pracujesz wyłącznie nad tym modułem.

## 1. Najpierw kontekst (bez zmian w kodzie)
Przeczytaj:
- ARCHITECTURE.md — zwłaszcza §3 (architektura E2E), §4 (warstwa danych),
- m2_scraper/TASK_SPEC.md — Twoja lista zadań, kontrakty i Definition of Done,
- shared/models.py (Event, Category, stable_id, normalize_tag, fold_text, is_in_krakow, INTEREST_TAGS), shared/storage.py (upsert_events), shared/mock_data.py (KRAKOW_VENUES),
- cały m2_scraper/ i jego testy.
Uruchom `pytest` i potwierdź, że jest zielony.

## 2. Pierwsze zadanie: rozpoznanie źródeł (M2-01) — bez pisania scrapera
Znajdź 3–4 kandydatów na źródło aktualnych wydarzeń w Krakowie (np. kalendarz Karnet Krakowskiego Biura Festiwalowego, strony instytucji: Filharmonia, Opera, MOCAK, teatry, kina studyjne). Dla każdego przygotuj tabelę: URL listy wydarzeń, co mówią robots.txt i regulamin, HTML czy JS (czy dane są w odpowiedzi requests), dostępne pola (tytuł, data, godzina, miejsce, adres, cena, kategoria, opis, link), stronicowanie, szacowany czas implementacji, ryzyka.
Pobieraj tylko pojedyncze strony, z przerwą ≥ 1 s. Zarekomenduj źródło główne i zapasowe, a potem ZATRZYMAJ SIĘ i poczekaj na moją decyzję.

## 3. Granice (twarde zasady)
- Edytujesz tylko: m2_scraper/** oraz data/seed_events.json.
- shared/** i foldery innych modułów są tylko do odczytu. Dodatkowe miejsca dopisuj w m2_scraper/venues.py, nie w shared/mock_data.py. Potrzebujesz zmiany w shared/? Zaproponuj minimalną zmianę ADDYTYWNĄ i zatrzymaj się na moją decyzję.
- Etyka i prawo: respektuj robots.txt i regulamin, nie obchodź logowania, CAPTCHA ani zabezpieczeń antybotowych, nie pobieraj danych osobowych. Jeśli źródło tego zabrania — odpuść je i powiedz mi o tym.
- Sieć: każde zapytanie przez PoliteHttp (User-Agent, opóźnienie ≥ 1 s, cache HTML na dysku). W trakcie developmentu pracuj na cache, nie odpytuj strony przy każdym uruchomieniu.
- Źródło (EventSource.fetch) NIGDY nie zapisuje do bazy — robi to wyłącznie run.py.
- Nowe zależności (np. playwright) tylko po mojej zgodzie; wtedy dopisz je do requirements.txt.

## 4. Sposób pracy
- Zadania w kolejności ID z TASK_SPEC: najpierw wszystkie MUST, potem SHOULD; COULD tylko na moją prośbę.
- Jedno zadanie naraz: krótki plan → implementacja → testy → weryfikacja → commit → raport.
- Parsery jako czyste funkcje (html → dane) testowane na fixture HTML: zapisz 1–2 prawdziwe strony do m2_scraper/fixtures/ i testuj offline w m2_scraper/tests/.
- Po każdym zadaniu cały `pytest` musi być zielony. Testy działają offline (bez sieci) i na Storage(":memory:") / fixture `empty_storage` — nigdy na data/app.db.
- Weryfikacja: `python -m m2_scraper.run --source <nazwa> --dry-run` oraz `streamlit run m2_scraper/sandbox.py` (w tle; zatrzymaj po sprawdzeniu).
- Commit po każdym zadaniu na bieżącej gałęzi, wiadomość „M2-0X: <co i po co>”. Nie pushuj i nie merguj do main bez mojej prośby.
- Raport po zadaniu: 1) co zrobione, 2) zmienione pliki, 3) wynik pytest, 4) statystyki danych (ile eventów, ile bez geo/ceny/tagów, rozkład kategorii), 5) otwarte kwestie.

## 5. Wskazówki techniczne dla M2
- Każde źródło = klasa w m2_scraper/sources/<nazwa>.py z atrybutem `name` i metodą `fetch() -> list[Event]`, zarejestrowana w SOURCES.
- Każdy Event: id = stable_id("ev", <nazwa źródła>, <url wydarzenia>), source = "scraper:<nazwa>", start/end jako naiwny czas lokalny (Europe/Warsaw), lat/lon w KRAKOW_BBOX, kategoria zmapowana na Category (w razie wątpliwości OTHER).
- Tagi decydują o jakości matchingu (M4): słownik słów kluczowych → tagi z INTEREST_TAGS, zawsze przez normalize_tag. Cel: ≥ 90% eventów z ≥ 1 tagiem.
- Polskie daty: miesiące w dopełniaczu i skrótach („10 października”, „10 paź”), dni tygodnia, zakresy („10–12.10”), brak roku → najbliższa przyszła data. Ceny: „wstęp wolny”/„bezpłatne” → 0, „od 40 zł” → 40, brak → None. Pokryj to testami tabelarycznymi.
- Geokodowanie (M2-04): kolejność KRAKOW_VENUES + m2_scraper/venues.py → cache → Nominatim. Zasady Nominatim: maks. 1 zapytanie/s, identyfikujący User-Agent, cache wszystkich wyników (także pustych), parametry countrycodes=pl, viewbox z KRAKOW_BBOX, bounded=1; wynik sprawdź przez is_in_krakow.
- Snapshot na demo (M2-06): `python -m m2_scraper.run --source <x> --export data/seed_events.json` oraz źródło "seed" ładujące ten plik przez ManualJsonSource — demo musi działać bez internetu.
- Integracja: przy działającym `streamlit run app.py` uruchom pipeline — Storage wykryje zapis z innego procesu (PRAGMA data_version) i nowe pinezki pojawią się bez restartu aplikacji.

## 6. Koniec modułu
Zanim zgłosisz „gotowe”, przejdź checklistę Definition of Done z TASK_SPEC §5 i dla każdego punktu podaj dowód (test, komenda, statystyki).
````

## Prompt na kolejne zadanie

````text
Zrealizuj zadanie M2-0X z m2_scraper/TASK_SPEC.md. Obowiązują zasady z początku sesji. Najpierw plan w 2–3 zdaniach, potem implementacja, testy (cały pytest, offline), commit „M2-0X: …” i raport w 5 punktach ze statystykami danych.
````
