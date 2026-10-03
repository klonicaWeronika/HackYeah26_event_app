# M2 — Scraper eventów i zasilanie bazy

Specyfikacja zadań: [TASK_SPEC.md](TASK_SPEC.md).

```bash
python -m m2_scraper.run --source karnet --dry-run     # pobierz + zwaliduj, bez zapisu
python -m m2_scraper.run --source all                  # wszystkie scrapery -> data/app.db
streamlit run m2_scraper/sandbox.py                    # podgląd wyniku źródła bez zapisu
```

## Decyzja o źródłach (M2-01, 2026-10-03)

| Rola | Źródło | Dostęp | Co daje |
|---|---|---|---|
| **Główne** | [Karnet — Krakowskie Biuro Festiwalowe](https://karnet.krakowculture.pl/wydarzenia) | HTML (Yii, render po stronie serwera), `?Item_page=N` | ~20–25 eventów dziennie, wszystkie kategorie kultury, **lat/lon na liście**, cena i opis na stronie szczegółów |
| Uzupełniające / zapasowe | [TAURON Arena Kraków](https://www.tauronarenakrakow.pl/wydarzenia/) | JSON: `/wp-json/tribe/events/v1/events` (The Events Calendar) | sport, duże koncerty, stand-up |
| Uzupełniające / zapasowe | [Opera Krakowska](https://opera.krakow.pl/repertuar) | JSON: `/ajax/repertuar?year=&month=` | opera, balet, koncerty, warsztaty |
| Plan B | `ManualJsonSource` + snapshot `data/seed_events.json` | plik w repo | demo offline |

### Rozpoznanie

| | Karnet | TAURON Arena | Opera Krakowska |
|---|---|---|---|
| robots.txt | brak (404) → bez ograniczeń | `Disallow: /wp-admin/` | brak (soft-404) → bez ograniczeń |
| Regulamin serwisu | brak; „© Krakowskie Biuro Festiwalowe” | — | tylko regulamin biletów |
| JS? | nie | nie (REST API) | lista w JS, dane z publicznego endpointu JSON |
| Pola | tytuł, data+godzina, typ, miejsce+adres, lat/lon, lead, obrazek, link; cena+opis w szczegółach | tytuł, start/end, kategoria, opis, obrazek, link | tytuł, data+godzina, typ, scena, link, link do biletów |
| Ryzyka | niepełny łańcuch TLS (patrz niżej); typ „W gminach Metropolii” to miejscowości pod Krakowem; wydarzenia całoroczne | 1 lokalizacja, brak cen | Cloudflare przed serwisem; endpoint nieudokumentowany; 1 lokalizacja |

**Odrzucone:** Filharmonia Krakowska — `403` dla identyfikującego się User-Agenta (ochrona antybotowa,
nie obchodzimy jej; koncerty Filharmonii są i tak w Karnecie). `krakow.pl/kalendarium` — wyświetla dane Karnetu.

### Zasady (etyka i prawo)

- Każde zapytanie przez `PoliteHttp`: identyfikujący User-Agent, ≥ 1 s przerwy, sprawdzenie `robots.txt`,
  cache odpowiedzi na dysku (`data/cache/http/`, gitignore).
- Nie obchodzimy logowania, CAPTCHA ani ochrony antybotowej — 403/challenge = rezygnujemy ze źródła.
- Bierzemy fakty (tytuł, termin, miejsce, cena) + krótki opis, zawsze z linkiem do strony źródłowej. Bez danych osobowych.
- **Geokodowanie (M2-04):** słownik `KRAKOW_VENUES` + `m2_scraper/venues.py` (98 miejsc ze współrzędnymi
  podanymi przez Karnet) → cache `data/cache/geocode.json` → Nominatim. **robots.txt Nominatim zawiera
  `Disallow: /search`**, więc zgodnie z zasadą „respektujemy robots.txt” geokoder go nie odpytuje (kod jest gotowy
  i sam się włączy, gdy robots na to pozwoli). Nie przeszkadza to: Karnet podaje lat/lon dla 99,7% wydarzeń.
- **TLS Karnetu:** serwer wysyła zły certyfikat pośredni (R29 zamiast E29). Publiczny certyfikat
  „nazwaSSL DV TLS G2 E29 CA” (z adresu AIA w certyfikacie serwera) leży w `m2_scraper/certs/` i jest dokładany do
  bundla `certifi` — weryfikacja TLS pozostaje włączona (nigdy `verify=False`).
