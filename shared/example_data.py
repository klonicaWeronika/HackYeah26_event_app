"""
shared/example_data.py — przykładowa społeczność na PRAWDZIWYCH wydarzeniach ze scrapera (M2).

Scraper daje wydarzenia (data/seed_events.json), ale nie ludzi: bez tej warstwy prawdziwe eventy mają
„Bądź pierwszy”, pusty czat i zero dopasowań. Ten moduł dokłada (wszystko FIKCYJNE):

  * 92 osoby z zainteresowaniami ze słownika tagów scrapera (teatr, opera, hip-hop, dla dzieci, …),
  * zapisy na nadchodzące eventy ze scrapera — każdy wybiera wydarzenia po wspólnych tagach,
    więc popularne koncerty i festiwale zbierają więcej osób, a niszowe spektakle 1–2 osoby,
  * tłum (CROWD_SIZES: od 60 do 30 osób) na CROWD_EVENTS najgorętszych eventach — żywe screeny i demo,
  * kilka zapisów person demo (Ola, Kuba, …) na prawdziwe eventy — Ola ma je w planach,
  * czaty najpopularniejszych wydarzeń + prywatne rozmowy (DM) Oli i Kuby.

Mocków (e_*) nie dotyka, a persony demo nie spotykają się ze sobą na prawdziwych eventach —
scenariusz z ARCHITECTURE.md §11 i złote testy M4 działają bez zmian.
Wejście to tylko lista eventów i osób -> działa po każdym odświeżeniu snapshotu (inne ID eventów).
Deterministyczne: te same eventy + ten sam dzień -> te same dane (random.Random z ziarnem-napisem).

Użycie:  python -m shared.storage --example     (dołóż do istniejącej bazy; --reset robi to sam)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TypeVar

from shared.models import (
    Attendance,
    AttendanceStatus,
    Category,
    ChatMessage,
    Event,
    User,
    dm_room_id,
    event_room_id,
    fold_text,
)

T = TypeVar("T")

SEED = "krk-razem-example-v1"
HORIZON_DAYS = 21                  # zapisy tylko na eventy z najbliższych 3 tygodni (i trwające)
PLANS_PER_USER = (10, 18)          # ile wydarzeń w planach ma osoba ze społeczności
PLANS_PER_PERSONA = (2, 4)         # ile prawdziwych eventów dostaje persona demo
CHAT_ROOMS = 12                    # tyle czatów wydarzeń z rozmową
CHAT_SOON_DAYS = 3                 # eventy z najbliższych dni mają pierwszeństwo przy czatach
CROWD_EVENTS = 6                   # tyle najgorętszych eventów dostaje tłum (żywe screeny i demo)
CROWD_SIZES = (60, 30)             # zapisani na najgorętszym … na ostatnim z nich (liniowo)
CROWD_RANDOM_WEIGHT = 0.3          # waga osoby bez wspólnego tagu przy dobieraniu tłumu (1 tag = +1)
INTERESTED_SHARE = 0.2             # część zapisów „Interesuje mnie” zamiast „Idę!”
HIDDEN_SHARE = 0.08                # część zapisów bez zgody na pokazanie w dopasowaniach

# (id, imię, płeć zdjęcia, nr zdjęcia na randomuser.me, bio, tagi)
_COMMUNITY: list[tuple] = [
    ("u_agata", "Agata", "women", 44, "Aktorka-amatorka. Na spektaklach bywam częściej niż w domu.",
     ["teatr", "literatura", "taniec", "sztuka współczesna", "wino"]),
    ("u_kamil", "Kamil", "men", 32, "Rap, koncerty pod sceną i mecze w weekend.",
     ["hip-hop", "pop", "rock", "stand-up", "piłka nożna"]),
    ("u_weronika", "Weronika", "women", 65, "Tańczę w zespole baletowym. Opera to mój drugi dom.",
     ["opera", "klasyka", "taniec", "historia", "kawa"]),
    ("u_szymon", "Szymon", "men", 46, "Kontrabasista. Jazz, folk i stare płyty z antykwariatów.",
     ["jazz", "folk", "klasyka", "literatura", "fotografia"]),
    ("u_magda", "Magda", "women", 17, "Mama pięciolatka — szukam spektakli dla dzieci i rodziców do wyjść.",
     ["dla dzieci", "teatr", "natura", "spacery", "rękodzieło"]),
    ("u_pawel", "Paweł", "men", 75, "Dev i hackathonowiec. Po pracy nauka, rano bieganie.",
     ["technologia", "startupy", "python", "nauka", "bieganie"]),
    ("u_ewa", "Ewa", "women", 33, "Graficzka. Galerie, kino studyjne i analogowa fotografia.",
     ["sztuka współczesna", "design", "fotografia", "architektura", "kino"]),
    ("u_igor", "Igor", "men", 11, "Produkuję muzykę elektroniczną. W weekendy tańczę do rana.",
     ["techno", "taniec", "design", "gry wideo"]),
    ("u_karolina", "Karolina", "women", 29, "Śmieję się najgłośniej na sali. Uczę się włoskiego.",
     ["stand-up", "kino", "pop", "street food", "języki obce"]),
    ("u_wojtek", "Wojtek", "men", 52, "Historyk z zamiłowania. Kraków znam od podwórek.",
     ["historia", "architektura", "spacery", "literatura", "rower"]),
    ("u_hania", "Hania", "women", 90, "Studiuję polonistykę. Teatr, poezja i dużo kawy.",
     ["literatura", "teatr", "kawa", "kino", "historia"]),
    ("u_mateusz", "Mateusz", "men", 22, "Gitara, indie i wieczory z planszówkami.",
     ["rock", "indie", "kino", "planszówki", "fotografia"]),
    ("u_dominika", "Dominika", "women", 57, "Instruktorka tańca. Pop, hip-hop i joga na rozluźnienie.",
     ["taniec", "pop", "hip-hop", "joga"]),
    ("u_krzysztof", "Krzysztof", "men", 64, "Melomaniak. Abonament w Filharmonii od dziesięciu lat.",
     ["klasyka", "opera", "historia", "wino"]),
    ("u_ula", "Ula", "women", 8, "Biolożka. Ogrody, eksperymenty i rodzinne wycieczki rowerowe.",
     ["natura", "nauka", "dla dzieci", "spacery", "rower"]),
    ("u_adrian", "Adrian", "men", 36, "Stand-up, rock i teatr — byle na żywo.",
     ["stand-up", "rock", "teatr", "kino"]),
    ("u_gosia", "Gosia", "women", 79, "Śpiewam w chórze, robię ceramikę, kocham folk.",
     ["folk", "jazz", "rękodzieło", "taniec"]),
    ("u_filip", "Filip", "men", 83, "Doktorant fizyki. Popularnonaukowe wykłady i gry.",
     ["nauka", "technologia", "kino", "gry wideo"]),
    ("u_iga", "Iga", "women", 42, "Scenografka. Teatr tańca i sztuka, która coś zmienia.",
     ["teatr", "taniec", "sztuka współczesna", "design"]),
    ("u_rafal", "Rafał", "men", 60, "Fan koncertów od lat 90. Jazz, rock i dobre historie.",
     ["jazz", "rock", "pop", "historia"]),
    ("u_sara", "Sara", "women", 24, "Erasmus z Walencji 🇪🇸 Uczę się polskiego, chodzę na wszystko.",
     ["języki obce", "taniec", "pop", "street food", "teatr"]),
    ("u_antoni", "Antoni", "men", 71, "Emerytowany nauczyciel. Opera, historia i długie spacery.",
     ["klasyka", "opera", "historia", "literatura", "spacery"]),
    ("u_nina", "Nina", "women", 51, "Recenzentka filmowa. Kino, książki, indie na winylu.",
     ["kino", "literatura", "sztuka współczesna", "indie"]),
    ("u_oskar", "Oskar", "men", 18, "Bity, gry i nocne zapiekanki na Kazimierzu.",
     ["hip-hop", "techno", "gry wideo", "street food"]),
    ("u_lena", "Lena", "women", 63, "Bibliotekarka i mama bliźniaków. Teatr lalek to nasz rytuał.",
     ["dla dzieci", "teatr", "literatura", "kawa"]),
    ("u_emil", "Emil", "men", 41, "Biegam maratony, jeżdżę rowerem, pracuję w IT.",
     ["bieganie", "rower", "natura", "technologia"]),
    ("u_patrycja", "Patrycja", "women", 12, "Fotografuję balet i operę zza kulis.",
     ["opera", "taniec", "klasyka", "fotografia"]),
    ("u_dawid", "Dawid", "men", 27, "Scenarzysta. Teatr, stand-up i historia w każdej formie.",
     ["teatr", "stand-up", "literatura", "historia"]),
    # --- tłum na screeny: kolejne osoby, zainteresowania zbliżone do tagów prawdziwych eventów ---
    ("u_alicja", "Alicja", "women", 1, "Studentka aktorstwa. W teatrze bywam kilka razy w tygodniu.",
     ["teatr", "literatura", "taniec", "kino"]),
    ("u_basia", "Basia", "women", 2, "Polonistka w liceum. Zabieram uczniów na spektakle i spotkania autorskie.",
     ["teatr", "literatura", "historia", "kawa"]),
    ("u_celina", "Celina", "women", 3, "Emerytowana pianistka. Filharmonia w każdy piątek.",
     ["klasyka", "opera", "historia", "spacery"]),
    ("u_daria", "Daria", "women", 4, "Mama dwójki przedszkolaków. Szukam wyjść dla całej rodziny.",
     ["dla dzieci", "teatr", "natura", "spacery"]),
    ("u_ela", "Ela", "women", 5, "Księgowa z duszą artystki. Kabaret, stand-up i dobre kino.",
     ["stand-up", "kino", "teatr", "wino"]),
    ("u_ewelina", "Ewelina", "women", 6, "Doktorantka historii sztuki. Muzea, wystawy, architektura.",
     ["sztuka współczesna", "historia", "architektura", "fotografia"]),
    ("u_gabriela", "Gabriela", "women", 7, "Tańczę salsę i bachatę, chodzę na koncerty pop.",
     ["taniec", "pop", "street food", "języki obce"]),
    ("u_iwona", "Iwona", "women", 9, "Bibliotekarka. Spotkania autorskie to moje święto.",
     ["literatura", "teatr", "historia", "kawa"]),
    ("u_joanna", "Joanna", "women", 10, "UX designerka. Meetupy technologiczne i dobra kawa.",
     ["technologia", "design", "startupy", "kawa", "nauka"]),
    ("u_justyna", "Justyna", "women", 11, "Pielęgniarka. Po dyżurze najchętniej komedia albo koncert.",
     ["teatr", "pop", "stand-up", "kino"]),
    ("u_kasia", "Kasia", "women", 13, "Przewodniczka po Kazimierzu. Historia Krakowa od podszewki.",
     ["historia", "spacery", "architektura", "literatura"]),
    ("u_klaudia", "Klaudia", "women", 14, "Programistka Pythona. Hackathony, nauka i rower.",
     ["python", "technologia", "nauka", "rower"]),
    ("u_laura", "Laura", "women", 15, "Śpiewam w chórze akademickim. Opera i musicale.",
     ["opera", "klasyka", "teatr", "taniec"]),
    ("u_maja", "Maja", "women", 16, "Licealistka. Rap, festiwale i koncerty pod sceną.",
     ["hip-hop", "pop", "rock", "taniec"]),
    ("u_marysia", "Marysia", "women", 18, "Nauczycielka w przedszkolu. Teatrzyki lalkowe znam na pamięć.",
     ["dla dzieci", "teatr", "rękodzieło", "literatura"]),
    ("u_monika", "Monika", "women", 19, "Prawniczka. Wieczorem teatr albo Filharmonia.",
     ["teatr", "klasyka", "wino", "literatura"]),
    ("u_olga", "Olga", "women", 20, "Studentka biologii. Ogród botaniczny i wykłady popularnonaukowe.",
     ["natura", "nauka", "spacery", "fotografia"]),
    ("u_paulina", "Paulina", "women", 21, "Fotografka ślubna. Prywatnie: koncerty i teatr tańca.",
     ["fotografia", "taniec", "teatr", "rock"]),
    ("u_renata", "Renata", "women", 22, "Lekarka. Jazz na żywo i długie spacery Plantami.",
     ["jazz", "klasyka", "spacery", "kawa"]),
    ("u_roksana", "Roksana", "women", 23, "DJ-ka w weekendy. Techno, design i nocny Kraków.",
     ["techno", "taniec", "design", "street food"]),
    ("u_sylwia", "Sylwia", "women", 25, "Pracuję w HR. Stand-up to moja terapia.",
     ["stand-up", "kino", "pop", "wino"]),
    ("u_tamara", "Tamara", "women", 26, "Choreografka. Teatr ruchu i sztuka współczesna.",
     ["taniec", "teatr", "sztuka współczesna", "design"]),
    ("u_wanda", "Wanda", "women", 27, "Babcia trojga wnuków. Zabieram ich na każdy spektakl dla dzieci.",
     ["dla dzieci", "teatr", "historia", "literatura"]),
    ("u_zuzia", "Zuzia", "women", 28, "Studentka filmoznawstwa. Kino studyjne i festiwale.",
     ["kino", "literatura", "sztuka współczesna", "indie"]),
    ("u_bianka", "Bianka", "women", 30, "Erasmus z Mediolanu 🇮🇹 Uczę się polskiego przez teatr.",
     ["języki obce", "teatr", "opera", "street food"]),
    ("u_dorota", "Dorota", "women", 31, "Mama nastolatka. Razem chodzimy na koncerty rockowe.",
     ["rock", "pop", "dla dzieci", "kino"]),
    ("u_kinga", "Kinga", "women", 32, "Data scientist. Meetupy, nauka i planszówki po pracy.",
     ["technologia", "nauka", "python", "planszówki"]),
    ("u_lidia", "Lidia", "women", 34, "Aktorka Teatru Ludowego. Na widowni też bywam często.",
     ["teatr", "literatura", "taniec", "historia"]),
    ("u_milena", "Milena", "women", 35, "Architektka. Spacery po Nowej Hucie i wystawy.",
     ["architektura", "historia", "sztuka współczesna", "spacery"]),
    ("u_oliwia", "Oliwia", "women", 36, "Studiuję etnologię. Folk, rękodzieło i muzyka świata.",
     ["folk", "rękodzieło", "taniec", "historia"]),
    ("u_pola", "Pola", "women", 37, "Copywriterka. Poezja slam, stand-up i kawiarnie.",
     ["literatura", "stand-up", "kawa", "teatr"]),
    ("u_wiktoria", "Wiktoria", "women", 38, "Biegam półmaratony, kocham przyrodę i koncerty.",
     ["bieganie", "natura", "pop", "rock"]),
    ("u_cezary", "Cezary", "men", 1, "Inżynier. Opera i muzyka klasyczna od dziecka.",
     ["opera", "klasyka", "historia", "technologia"]),
    ("u_damian", "Damian", "men", 2, "Trener personalny. Rock, mecze i bieganie.",
     ["rock", "piłka nożna", "bieganie", "hip-hop"]),
    ("u_dominik", "Dominik", "men", 3, "Student informatyki. Hackathony to moje weekendy.",
     ["technologia", "python", "startupy", "gry wideo"]),
    ("u_grzegorz", "Grzegorz", "men", 4, "Tata dwóch córek. Teatr lalek i wycieczki rowerowe.",
     ["dla dzieci", "teatr", "rower", "natura"]),
    ("u_hubert", "Hubert", "men", 5, "Historyk wojskowości. Muzea i spotkania z autorami.",
     ["historia", "literatura", "architektura", "spacery"]),
    ("u_jacek", "Jacek", "men", 6, "Saksofonista amator. Jam session w piwnicach Kazimierza.",
     ["jazz", "folk", "klasyka", "wino"]),
    ("u_jan", "Jan", "men", 7, "Student prawa. Teatr, debaty i dobre książki.",
     ["teatr", "literatura", "historia", "kino"]),
    ("u_kacper", "Kacper", "men", 8, "Produkuję bity. Hip-hop i techno do rana.",
     ["hip-hop", "techno", "gry wideo", "street food"]),
    ("u_karol", "Karol", "men", 9, "Aktor dubbingowy. Kino i teatr to mój chleb.",
     ["teatr", "kino", "stand-up", "literatura"]),
    ("u_konrad", "Konrad", "men", 10, "Fizyk. Noc Naukowców to mój ulubiony dzień w roku.",
     ["nauka", "technologia", "natura", "kino"]),
    ("u_maciej", "Maciej", "men", 12, "Gitarzysta zespołu coverowego. Rock i pop na żywo.",
     ["rock", "pop", "indie", "planszówki"]),
    ("u_marek", "Marek", "men", 13, "Nauczyciel historii. Zabytki, książki i Filharmonia.",
     ["historia", "klasyka", "literatura", "architektura"]),
    ("u_mikolaj", "Mikołaj", "men", 14, "Licealista. Stand-up, gry i koncerty pod sceną.",
     ["stand-up", "gry wideo", "hip-hop", "pop"]),
    ("u_norbert", "Norbert", "men", 15, "Kucharz. Street food, wino i jazz po godzinach.",
     ["street food", "wino", "jazz", "kino"]),
    ("u_olaf", "Olaf", "men", 16, "Student z Oslo 🇳🇴 Learning Polish, love theatre and techno.",
     ["języki obce", "teatr", "techno", "historia"]),
    ("u_patryk", "Patryk", "men", 17, "Kierowca tramwaju. Rock, mecze i kino akcji.",
     ["rock", "piłka nożna", "kino", "stand-up"]),
    ("u_przemek", "Przemek", "men", 19, "Backend developer. Meetupy, startupy i rower.",
     ["technologia", "startupy", "rower", "python"]),
    ("u_robert", "Robert", "men", 20, "Tata trojga. Spektakle dla dzieci w każdy weekend.",
     ["dla dzieci", "teatr", "natura", "historia"]),
    ("u_sebastian", "Sebastian", "men", 21, "Tancerz baletowy. Opera, balet i teatr tańca.",
     ["taniec", "opera", "klasyka", "teatr"]),
    ("u_stanislaw", "Stanisław", "men", 23, "Emerytowany inżynier. Opera, historia i spacery po Plantach.",
     ["opera", "historia", "spacery", "klasyka"]),
    ("u_tymon", "Tymon", "men", 24, "Student reżyserii. Teatr, kino i literatura.",
     ["teatr", "kino", "literatura", "sztuka współczesna"]),
    ("u_wiktor", "Wiktor", "men", 25, "Startupowiec. Networking, technologia i bieganie.",
     ["startupy", "technologia", "bieganie", "nauka"]),
    ("u_witold", "Witold", "men", 26, "Krytyk teatralny. Widzę każdą premierę w Krakowie.",
     ["teatr", "literatura", "opera", "historia"]),
    ("u_aleksander", "Aleksander", "men", 28, "Student historii. Rekonstrukcje i muzea.",
     ["historia", "architektura", "literatura", "gry wideo"]),
    ("u_artur", "Artur", "men", 29, "Perkusista. Rock, jazz i koncerty w klubach.",
     ["rock", "jazz", "indie", "street food"]),
    ("u_borys", "Borys", "men", 30, "Projektant gier. Stand-up, kino i planszówki.",
     ["gry wideo", "planszówki", "stand-up", "kino"]),
    ("u_daniel", "Daniel", "men", 31, "Ratownik medyczny. Po pracy natura i bieganie.",
     ["natura", "bieganie", "rower", "spacery"]),
    ("u_ignacy", "Ignacy", "men", 33, "Student filozofii. Teatr, poezja i jazz.",
     ["teatr", "literatura", "jazz", "kawa"]),
    ("u_julian", "Julian", "men", 34, "Fotograf koncertowy. Rock, hip-hop i techno.",
     ["fotografia", "rock", "hip-hop", "techno"]),
    ("u_leon", "Leon", "men", 35, "Tata pięciolatki. Teatrzyki, warsztaty i ogrody.",
     ["dla dzieci", "rękodzieło", "natura", "teatr"]),
    ("u_marcin", "Marcin", "men", 37, "Nauczyciel fizyki. Nauka, technologia i kino science fiction.",
     ["nauka", "technologia", "kino", "dla dzieci"]),
    ("u_nikodem", "Nikodem", "men", 38, "Student muzykologii. Klasyka, opera i folk.",
     ["klasyka", "opera", "folk", "literatura"]),
]

_PERSONA_ORDER = ["u_ola", "u_bartek", "u_natalia", "u_kuba", "u_marta", "u_ania", "u_zosia",
                  "u_piotr", "u_michal", "u_tomek", "u_julia", "u_lukas"]

# Mnożnik „popularności” kategorii (ile osób przyciąga podobny event).
_CATEGORY_HEAT: dict[Category, float] = {
    Category.MUSIC: 1.6, Category.FESTIVAL: 1.6, Category.SPORT: 1.4, Category.MEETUP: 1.4,
    Category.CINEMA: 1.1, Category.EXHIBITION: 1.0, Category.WORKSHOP: 1.0, Category.OUTDOOR: 1.2,
    Category.FOOD: 1.2, Category.THEATRE: 0.8, Category.OTHER: 0.9,
}
_TECH_TAGS = {"technologia", "startupy", "python", "nauka"}
_BIG_VENUES = {"scraper:tauron": 2.5, "scraper:opera": 2.0}   # duże sceny przyciągają tłum
# Wydarzenia, które na demo mają mieć tłum (fragment tytułu bez polskich znaków -> mnożnik popularności).
_HEADLINERS: dict[str, float] = {"hackyeah": 12.0}


# --------------------------------------------------------------------------- #
# Szablony rozmów: (numer rozmówcy, tekst). {meet} = godzina zbiórki (20 min przed startem).
# Teksty bez form zależnych od płci mówiącego — rozmówców losujemy z zapisanych.
# --------------------------------------------------------------------------- #

_CHATS: dict[str, list[tuple[int, str]]] = {
    "music": [
        (0, "Ktoś jeszcze idzie bez ekipy? Chętnie dołączę 🙂"),
        (1, "Jest nas już kilkoro! Zbiórka o {meet} przed wejściem?"),
        (2, "Pasuje. Będę w zielonej kurtce 🧥"),
        (0, "Super. A po koncercie może coś ciepłego do picia w okolicy?"),
        (3, "Wchodzę w to ☕ Podobno nagłośnienie jest tam świetne."),
        (1, "To do zobaczenia o {meet}! 🎶"),
    ],
    "opera": [
        (0, "Pierwszy raz w operze — jak się ubrać? 😅"),
        (1, "Elegancko, ale bez przesady. Koszula albo sukienka w zupełności wystarczą."),
        (2, "Warto przyjść wcześniej, przed spektaklem jest krótkie wprowadzenie."),
        (0, "Dzięki! To widzimy się o {meet} przy szatni?"),
        (1, "Tak! 🎼"),
    ],
    "theatre": [
        (0, "Hej! Ktoś już widział ten spektakl? Warto?"),
        (1, "Tak, na premierze — mocna druga część, scenografia robi wrażenie."),
        (2, "Mam jeden dodatkowy bilet (rząd 7). Ktoś chętny po cenie z kasy?"),
        (3, "Ja chętnie! Odezwę się na priv 🙏"),
        (0, "To może spotkanie w foyer o {meet}? Łatwiej będzie się znaleźć."),
        (2, "Jasne, do zobaczenia 🎭"),
    ],
    "kids": [
        (0, "Czy ktoś idzie z dziećmi? Mój pięciolatek uwielbia lalki 🧸"),
        (1, "My też! Córka ma 6 lat. Może usiądziemy razem?"),
        (2, "Polecamy — byliśmy wiosną, dzieci zachwycone."),
        (0, "To widzimy się o {meet} przy wejściu 👋"),
    ],
    "festival": [
        (0, "Na które wydarzenia festiwalu się wybieracie?"),
        (1, "Głównie weekend — podobno sobotni program jest najmocniejszy."),
        (2, "Też! Możemy iść razem, zbieramy małą ekipę 🙌"),
        (0, "Świetnie, dopisujcie się tutaj, szczegóły ustalimy bliżej terminu."),
        (3, "Dopisuję się 🙋"),
    ],
    "cinema": [
        (0, "Ktoś idzie na ten seans? Szukam towarzystwa 🍿"),
        (1, "Ja! Bilety jeszcze są, środkowe rzędy wolne."),
        (2, "Po seansie dyskusja przy herbacie? 😄"),
        (0, "Brzmi idealnie. Zbiórka o {meet} w holu."),
    ],
    "tech": [
        (0, "Hej! Ktoś jeszcze szuka drużyny albo jednej osoby do zespołu? 💻"),
        (1, "My! Robimy mapę wydarzeń Krakowa w Streamlicie, przyda się ktoś od UX."),
        (2, "Brzmi świetnie, podejdę do Was po otwarciu. Gdzie siedzicie?"),
        (1, "Sektor B, stolik przy oknie. Szukajcie pomarańczowego logo 🧡"),
        (3, "Kawa przy wejściu jest najlepsza — warto zdążyć przed kolejką ☕"),
        (0, "Dzięki, do zobaczenia!"),
    ],
    "sport": [
        (0, "Jakie tempo planujecie? Celuję w okolice 5:30/km."),
        (1, "Raczej spokojnie, 6:00/km. Może pobiegniemy razem?"),
        (2, "Zbiórka przy starcie o {meet}? Zrobimy wspólną rozgrzewkę 🏃"),
        (0, "Jasne! A po biegu kawa 😄"),
    ],
    "default": [
        (0, "Hej! Ktoś jeszcze się wybiera? Chętnie poznam nowe osoby 🙂"),
        (1, "Ja! Pierwszy raz na takim wydarzeniu."),
        (2, "Też idę. Spotkajmy się o {meet} przy wejściu."),
        (0, "Super, do zobaczenia!"),
    ],
}

# Prywatne rozmowy: (0 = persona demo, 1 = osoba ze społeczności, tekst). {title} = tytuł eventu.
_DMS: list[list[tuple[int, str]]] = [
    [
        (1, "Cześć! Widzę, że też idziesz na „{title}” 🙂"),
        (0, "Hej! Tak, pierwszy raz na czymś takim w Krakowie."),
        (1, "To może spotkamy się wcześniej na kawie? Znam miejsce dwa kroki obok."),
        (0, "Chętnie! {meet} przy wejściu?"),
        (1, "Pasuje, do zobaczenia 👋"),
    ],
    [
        (0, "Hej! Aplikacja dopasowała nas na „{title}” — sporo wspólnych zainteresowań 😄"),
        (1, "No właśnie widzę! Idziesz z kimś?"),
        (0, "Jeszcze nie, dlatego piszę 🙂"),
        (1, "To idziemy razem. Wrzucę jeszcze info na czat wydarzenia."),
    ],
]


@dataclass
class ExampleDataset:
    users: list[User] = field(default_factory=list)
    attendance: list[Attendance] = field(default_factory=list)
    messages: list[ChatMessage] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Budowa
# --------------------------------------------------------------------------- #


def community_users(reference_now: datetime | None = None) -> list[User]:
    reference_now = reference_now or datetime.now().replace(microsecond=0)
    return [
        User(id=uid, name=name, bio=bio, tags=tags,
             avatar_url=f"https://randomuser.me/api/portraits/{sex}/{img}.jpg",
             created_at=reference_now - timedelta(days=random.Random(f"{SEED}:{uid}").randint(3, 60)))
        for uid, name, sex, img, bio, tags in _COMMUNITY
    ]


def _candidates(events: list[Event], today: date) -> list[Event]:
    """Nadchodzące (i trwające) eventy ze scrapera w horyzoncie — tylko na nie dokładamy ludzi."""
    last_day = today + timedelta(days=HORIZON_DAYS)
    return [
        e for e in events
        if e.source.startswith("scraper:") and e.end_or_start.date() >= today and e.start.date() <= last_day
    ]


def _heat(event: Event, today: date) -> float:
    """Popularność eventu: kategoria × bliskość terminu × duża scena × headliner × losowy „szum”
    (stały dla eventu)."""
    days = max((event.start.date() - today).days, 0)
    soon = 2.0 if days == 0 else 1.6 if days <= 3 else 1.0 if days <= 10 else 0.6
    title = fold_text(event.title)
    headliner = max((boost for key, boost in _HEADLINERS.items() if key in title), default=1.0)
    sigma = 0.5 if event.source in _BIG_VENUES else 1.2    # duża scena = przewidywalnie popularna
    noise = random.Random(f"{SEED}:heat:{event.id}").lognormvariate(0, sigma)
    return (_CATEGORY_HEAT.get(event.category, 1.0) * soon * _BIG_VENUES.get(event.source, 1.0)
            * headliner * noise)


def _weighted_sample(rng: random.Random, items: list[T], weights: list[float], k: int) -> list[T]:
    """k elementów bez powtórzeń, z prawdopodobieństwem ∝ waga (Efraimidis–Spirakis)."""
    keyed = [(rng.random() ** (1.0 / w), i) for i, w in enumerate(weights) if w > 0]
    keyed.sort(reverse=True)
    return [items[i] for _, i in keyed[:k]]


def _crowd_targets(pool: list[Event], heat: dict[str, float]) -> list[tuple[Event, int]]:
    """CROWD_EVENTS najgorętszych eventów z docelową liczbą zapisanych (od CROWD_SIZES[0] do [1])."""
    hottest = sorted(pool, key=lambda e: (-heat[e.id], e.start, e.id))[:CROWD_EVENTS]
    big, small = CROWD_SIZES
    step = (big - small) / max(len(hottest) - 1, 1)
    return [(event, round(big - i * step)) for i, event in enumerate(hottest)]


def _pick_events(user: User, pool: list[Event], heat: dict[str, float], k: int) -> list[Event]:
    rng = random.Random(f"{SEED}:plans:{user.id}")
    tags = set(user.tags)
    weights = [(len(tags.intersection(e.tags)) ** 2 or 0.05) * heat[e.id] for e in pool]
    return _weighted_sample(rng, pool, weights, k)


def _attendance(user_id: str, event_id: str, rng: random.Random, now: datetime) -> Attendance:
    return Attendance(
        user_id=user_id, event_id=event_id,
        status=AttendanceStatus.INTERESTED if rng.random() < INTERESTED_SHARE else AttendanceStatus.GOING,
        open_to_meet=rng.random() >= HIDDEN_SHARE,
        created_at=now - timedelta(hours=rng.randint(1, 240)),
    )


def _chat_kind(event: Event) -> str:
    tags = set(event.tags)
    if "dla dzieci" in tags:
        return "kids"
    if event.category in (Category.MEETUP, Category.WORKSHOP) and tags & _TECH_TAGS:
        return "tech"
    if "opera" in tags and event.category is Category.MUSIC:
        return "opera"
    return {
        Category.MUSIC: "music", Category.THEATRE: "theatre", Category.FESTIVAL: "festival",
        Category.CINEMA: "cinema", Category.SPORT: "sport",
    }.get(event.category, "default")


def _meet_time(event: Event) -> str:
    start = event.start
    if start.time() == datetime.min.time():           # event bez godziny (np. festiwal) -> umowna 18:00
        start = start.replace(hour=18)
    return (start - timedelta(minutes=20)).strftime("%H:%M")


def _conversation(
    room_id: str, script: list[tuple[int, str]], speakers: list[str], event: Event,
    rng: random.Random, now: datetime, first_id: int,
) -> list[ChatMessage]:
    """Rozmowa rozłożona w czasie: start 6–40 h temu, kolejne wiadomości co kilka–kilkadziesiąt minut."""
    gaps = [rng.randint(4, 150) for _ in script[1:]]
    started = now - timedelta(minutes=sum(gaps) + rng.randint(30, 40 * 60))
    when, out = started, []
    for i, (speaker, text) in enumerate(script):
        if i:
            when += timedelta(minutes=gaps[i - 1])
        out.append(ChatMessage(
            id=f"msg_ex_{first_id + i:04d}", room_id=room_id, user_id=speakers[speaker % len(speakers)],
            text=text.format(meet=_meet_time(event), title=event.title), created_at=min(when, now),
        ))
    return out


def build_example_dataset(
    events: list[Event], personas: list[User], *, today: date | None = None,
    reference_now: datetime | None = None,
) -> ExampleDataset:
    """Społeczność + zapisy + czaty dla podanych eventów. `personas` = osoby już w bazie (mocki M3;
    społeczność z poprzedniego seeda jest pomijana)."""
    today = today or date.today()
    now = reference_now or datetime.now().replace(microsecond=0)
    pool = sorted(_candidates(events, today), key=lambda e: (e.start, e.id))
    users = community_users(now)
    if not pool:
        return ExampleDataset(users=users)
    heat = {e.id: _heat(e, today) for e in pool}

    attendance: dict[tuple[str, str], Attendance] = {}
    for user in users:
        rng = random.Random(f"{SEED}:count:{user.id}")
        for event in _pick_events(user, pool, heat, rng.randint(*PLANS_PER_USER)):
            attendance[(user.id, event.id)] = _attendance(user.id, event.id, rng, now)

    # Tłum na kilku najgorętszych eventach: dobieramy osoby ze społeczności do docelowej liczby —
    # częściej pasujące tagami, ale tłum to też ludzie „z przypadku”. Persony demo się tu nie dopisują.
    for event, size in _crowd_targets(pool, heat):
        going_now = {uid for (uid, eid) in attendance if eid == event.id}
        others = [u for u in users if u.id not in going_now]
        rng = random.Random(f"{SEED}:crowd:{event.id}")
        weights = [len(set(u.tags) & set(event.tags)) + CROWD_RANDOM_WEIGHT for u in others]
        for user in _weighted_sample(rng, others, weights, max(size - len(going_now), 0)):
            attendance[(user.id, event.id)] = _attendance(user.id, event.id, rng, now)

    # Persony demo: kilka prawdziwych eventów każda, ale nigdy dwie na tym samym (zero nowych
    # wspólnych wydarzeń między mockami -> ranking dopasowań w scenariuszu demo się nie zmienia).
    community_ids = {u.id for u in users}       # przy ponownym seedzie społeczność jest już w bazie
    by_id = {u.id: u for u in personas if u.id not in community_ids}
    persona_events: set[str] = set()
    for pid in [p for p in _PERSONA_ORDER if p in by_id]:
        rng = random.Random(f"{SEED}:persona:{pid}")
        free = [e for e in pool if e.id not in persona_events]
        for event in _pick_events(by_id[pid], free, heat, rng.randint(*PLANS_PER_PERSONA)):
            persona_events.add(event.id)
            attendance[(pid, event.id)] = _attendance(pid, event.id, rng, now).copy_with(
                status=AttendanceStatus.GOING, open_to_meet=True)

    going: dict[str, list[str]] = {}
    for (uid, eid) in sorted(attendance):
        going.setdefault(eid, []).append(uid)

    messages = _event_chats(pool, going, by_id, today, now)
    messages += _direct_messages(pool, users, by_id, attendance, now, first_id=len(messages))
    return ExampleDataset(users=users, attendance=list(attendance.values()), messages=messages)


def _event_chats(
    pool: list[Event], going: dict[str, list[str]], personas: dict[str, User], today: date, now: datetime,
) -> list[ChatMessage]:
    """Czaty: najpierw eventy z najbliższych dni, potem najpopularniejsze. Piszą tylko osoby spoza
    person demo (ich wiadomości w mockach są częścią scenariusza)."""
    def crowd(e: Event) -> list[str]:
        return [u for u in going.get(e.id, []) if u not in personas]

    rooms = [e for e in pool if len(crowd(e)) >= 3]
    soon = [e for e in rooms if (e.start.date() - today).days <= CHAT_SOON_DAYS]
    soon.sort(key=lambda e: (-len(crowd(e)), e.start, e.id))
    rest = sorted((e for e in rooms if e not in soon[: CHAT_ROOMS // 2]),
                  key=lambda e: (-len(crowd(e)), e.start, e.id))
    chosen = (soon[: CHAT_ROOMS // 2] + rest)[:CHAT_ROOMS]

    messages: list[ChatMessage] = []
    for event in chosen:
        rng = random.Random(f"{SEED}:chat:{event.id}")
        speakers = crowd(event)
        rng.shuffle(speakers)
        messages += _conversation(event_room_id(event.id), _CHATS[_chat_kind(event)], speakers, event,
                                  rng, now, first_id=len(messages))
    return messages


def _direct_messages(
    pool: list[Event], community: list[User], personas: dict[str, User],
    attendance: dict[tuple[str, str], Attendance], now: datetime, *, first_id: int,
) -> list[ChatMessage]:
    """DM-y: persona demo ↔ najlepiej pasująca osoba ze społeczności na jednym z prawdziwych eventów
    persony. Gdy ta osoba się na niego nie zapisała, dopisujemy ją (wtedy jest też w „Pasujących”)."""
    events = {e.id: e for e in pool}
    messages: list[ChatMessage] = []
    used: set[str] = set()
    for pid, script in (("u_ola", _DMS[0]), ("u_ola", _DMS[1]), ("u_kuba", _DMS[0])):
        persona = personas.get(pid)
        mine = [events[eid] for (uid, eid) in attendance if uid == pid]
        if persona is None or not mine:
            continue
        tags = set(persona.tags)
        # (wspólne tagi, już zapisana, wcześniejszy termin, id) — max wybiera najlepszą parę deterministycznie
        _, _, _, other_id, event_id = max(
            (len(tags & set(o.tags)), (o.id, e.id) in attendance, -e.start.timestamp(), o.id, e.id)
            for e in mine for o in community if o.id not in used
        )
        used.add(other_id)
        rng = random.Random(f"{SEED}:dm:{pid}:{other_id}")
        if (other_id, event_id) not in attendance:
            attendance[(other_id, event_id)] = _attendance(other_id, event_id, rng, now).copy_with(
                status=AttendanceStatus.GOING, open_to_meet=True)
        messages += _conversation(dm_room_id(pid, other_id), script, [pid, other_id], events[event_id],
                                  rng, now, first_id=first_id + len(messages))
    return messages


def summary(ds: ExampleDataset) -> str:
    rooms = {m.room_id for m in ds.messages}
    dms = sum(1 for r in rooms if r.startswith("dm:"))
    events = {a.event_id for a in ds.attendance}
    return (f"osoby={len(ds.users)} zapisy={len(ds.attendance)} (na {len(events)} eventach) "
            f"wiadomości={len(ds.messages)} czaty={len(rooms) - dms} DM={dms}")


__all__ = ["ExampleDataset", "build_example_dataset", "community_users", "summary"]
