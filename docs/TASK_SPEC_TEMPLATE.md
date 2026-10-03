# TASK_SPEC — M{N}: {Nazwa modułu}

> Szablon specyfikacji modułu. Każdy moduł ma swój egzemplarz w `m{N}_*/TASK_SPEC.md`.
> Zasada: **jeśli czegoś nie ma w sekcji 3 (Kontrakty), inne moduły nie mogą na tym polegać.**

| | |
|---|---|
| **Właściciel** | _imię (Dev N)_ |
| **Folder** | `m{N}_*/` |
| **Priorytet modułu** | CORE / OPCJONALNY |
| **Korzysta z** | `shared/...` (lista plików) |
| **Dostarcza dla** | M? (co konkretnie) |
| **Sandbox** | `streamlit run m{N}_*/sandbox.py` |
| **Testy** | `pytest m{N}_*` |

---

## 1. Cel

Jedno–dwa zdania: jaką wartość dla użytkownika dostarcza moduł na demo.

## 2. Zakres

### 2.1 Stan wyjściowy (co już działa w szkielecie)

Lista funkcji, które działają od godziny 0 (walking skeleton) — punkt startu, nie trzeba ich pisać od nowa.

### 2.2 Zadania atomowe

Priorytety: **MUST** = bez tego nie ma demo · **SHOULD** = mocno podnosi ocenę · **COULD** = tylko gdy MUST/SHOULD są gotowe.
Każde zadanie ≤ 3 h, ma jednoznaczne kryterium „gotowe gdy”.

| ID | Zadanie | Prio | Est. | Gotowe gdy |
|----|---------|------|------|------------|
| M{N}-01 | … | MUST | 1 h | … |

### 2.3 Poza zakresem

Czego ten moduł NIE robi (i kto to robi).

## 3. Kontrakty

### 3.1 Wejście (z `shared/`)

Modele i funkcje `shared/`, których moduł używa.

### 3.2 Wyjście — publiczne API (sygnatury zamrożone)

```python
# sygnatury, które wołają inne moduły; zmiana = PR + zgoda Leada
```

### 3.3 Stan sesji

| Klucz / funkcja `shared.state` | Czyta | Pisze |
|---|---|---|

Klucze prywatne modułu: prefiks `m{N}_`.

### 3.4 Pliki modułu (własność)

Pliki, które edytuje wyłącznie właściciel modułu.

## 4. Niezależne testowanie (mocki)

1. Dane: `Storage(":memory:")` / fixture `storage` z `conftest.py` (mocki Krakowa, stałe ID `e_*`, `u_*`).
2. Testy jednostkowe: `pytest m{N}_*` — lista kluczowych przypadków.
3. Sandbox UI: `streamlit run m{N}_*/sandbox.py` — co w nim sprawdzić.
4. Integracja: `streamlit run app.py` — ścieżka kliknięć.

## 5. Definition of Done (demo)

- [ ] Wszystkie zadania MUST zrobione.
- [ ] `pytest` zielony (cały projekt, nie tylko moduł).
- [ ] Sandbox i `app.py` uruchamiają się bez wyjątków na świeżej bazie (`python -m shared.storage --reset`).
- [ ] Brak lagów: interakcja w module < 300 ms (bez sieci).
- [ ] Kryteria specyficzne dla modułu: …

## 6. Ryzyka i plan B

| Ryzyko | Sygnał ostrzegawczy | Plan B |
|---|---|---|

## 7. Punkty synchronizacji

| Kiedy | Co musi być na `main` |
|---|---|
| H1 | … |
| H6 | … |
| H12 | … |
| H18 | … |
