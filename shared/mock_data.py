"""
shared/mock_data.py — realistyczne dane demo dla Krakowa.

* Prawdziwe miejsca (współrzędne przybliżone), FIKCYJNE wydarzenia i osoby.
* Daty liczone WZGLĘDEM DZISIAJ -> demo zawsze pokazuje nadchodzące eventy.
  Po kilku dniach pracy: `python -m shared.storage --reset` odświeża daty.
* ID są stałe (e_*, u_*), więc testy i sandboxy mogą się do nich odwoływać.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from shared.models import (
    Attendance,
    AttendanceStatus,
    Category,
    ChatMessage,
    Event,
    User,
    event_room_id,
)

DEMO_USER_ID = "u_ola"


@dataclass(frozen=True)
class Venue:
    name: str
    address: str
    lat: float
    lon: float


# Słownik miejsc — używany też przez geokoder M2 jako cache "znanych lokalizacji".
KRAKOW_VENUES: dict[str, Venue] = {
    "alchemia": Venue("Alchemia", "ul. Estery 5", 50.0518, 19.9449),
    "filharmonia": Venue("Filharmonia Krakowska", "ul. Zwierzyniecka 1", 50.0585, 19.9320),
    "studio": Venue("Klub Studio", "ul. Budryka 4", 50.0680, 19.9065),
    "forum": Venue("Forum Przestrzenie", "ul. Marii Konopnickiej 28", 50.0475, 19.9343),
    "tauron": Venue("TAURON Arena Kraków", "ul. Stanisława Lema 7", 50.0676, 19.9917),
    "opera": Venue("Opera Krakowska", "ul. Lubicz 48", 50.0656, 19.9572),
    "stary": Venue("Narodowy Stary Teatr", "ul. Jagiellońska 1", 50.0628, 19.9357),
    "slowacki": Venue("Teatr im. Juliusza Słowackiego", "pl. Świętego Ducha 1", 50.0645, 19.9420),
    "cricoteka": Venue("Cricoteka", "ul. Nadwiślańska 2-4", 50.0487, 19.9491),
    "pod_baranami": Venue("Kino Pod Baranami", "Rynek Główny 27", 50.0617, 19.9356),
    "kijow": Venue("Kino Kijów", "al. Krasińskiego 34", 50.0583, 19.9264),
    "manggha": Venue("Muzeum Manggha", "ul. Marii Konopnickiej 26", 50.0507, 19.9324),
    "mocak": Venue("MOCAK", "ul. Lipowa 4", 50.0475, 19.9617),
    "schindler": Venue("Fabryka Emalia Oskara Schindlera", "ul. Lipowa 4", 50.0477, 19.9612),
    "mnk": Venue("Muzeum Narodowe – Gmach Główny", "al. 3 Maja 1", 50.0603, 19.9238),
    "plac_nowy": Venue("Plac Nowy", "pl. Nowy, Kazimierz", 50.0514, 19.9447),
    "kopiec": Venue("Kopiec Kościuszki", "al. Waszyngtona 1", 50.0549, 19.8933),
    "plac_centralny": Venue("Plac Centralny", "pl. Centralny, Nowa Huta", 50.0719, 20.0377),
    "blonia": Venue("Błonia Krakowskie", "al. 3 Maja", 50.0596, 19.9135),
    "bulwary": Venue("Bulwar Czerwieński", "Bulwar Czerwieński", 50.0530, 19.9338),
    "jordana": Venue("Park Jordana", "al. 3 Maja 11", 50.0628, 19.9168),
    "agh": Venue("AGH – Budynek A0", "al. Mickiewicza 30", 50.0646, 19.9233),
    "ice": Venue("ICE Kraków", "ul. Marii Konopnickiej 17", 50.0478, 19.9328),
    "hevre": Venue("Hevre", "ul. Beera Meiselsa 18", 50.0517, 19.9433),
    "massolit": Venue("Massolit Books & Cafe", "ul. Felicjanek 4", 50.0573, 19.9304),
    "kwadrat": Venue("Klub Kwadrat", "ul. Skarżyńskiego 1", 50.0714, 20.0006),
    "zablocie": Venue("Pracownia na Zabłociu", "ul. Przemysłowa 12", 50.0469, 19.9586),
    "ogrod_lema": Venue("Ogród Doświadczeń im. S. Lema", "al. Pokoju 68", 50.0686, 19.9822),
    "lotnictwo": Venue("Muzeum Lotnictwa Polskiego", "al. Jana Pawła II 39", 50.0776, 19.9858),
    "rynek": Venue("Rynek Główny", "Rynek Główny", 50.0617, 19.9373),
    "winiarnia": Venue("Winiarnia przy Rynku", "ul. św. Tomasza 10", 50.0630, 19.9389),
    "palarnia": Venue("Palarnia kawy na Kazimierzu", "ul. Józefa 20", 50.0508, 19.9437),
    "wawel": Venue("Wzgórze Wawelskie", "Wawel 5", 50.0540, 19.9354),
    "stadion": Venue("Stadion Miejski im. H. Reymana", "ul. Reymonta 22", 50.0637, 19.9119),
}

# (id, tytuł, kategoria, tagi, dzień_offset, "HH:MM", czas_trwania_h, venue_key, cena_PLN, opis)
_EVENT_ROWS: list[tuple] = [
    ("e_jazz_alchemia", "Jam session jazzowy w piwnicy", Category.MUSIC, ["jazz"], 0, "20:00", 3, "alchemia", 20,
     "Otwarta scena dla muzyków i słuchaczy. Pierwszy set gra house band, potem jam."),
    ("e_wawel_legendy", "Spacer legend: Smok Wawelski i okolice", Category.OUTDOOR, ["historia", "spacery"], 0, "17:00", 1.5, "wawel", 0,
     "Kameralny spacer z przewodnikiem po legendach Wawelu. Zbiórka przy Bramie Herbowej."),
    ("e_mocak_wystawa", "Wystawa: Miasto jako organizm", Category.EXHIBITION, ["sztuka współczesna", "design"], -5, "10:00", 24 * 30, "mocak", 20,
     "Instalacje i wideo o tym, jak oddycha, rośnie i męczy się współczesne miasto."),
    ("e_stary_wesele", "Wesele — nowe odczytanie", Category.THEATRE, ["teatr", "literatura"], 1, "19:00", 2.5, "stary", 65,
     "Klasyk Wyspiańskiego w odważnej, współczesnej inscenizacji."),
    ("e_rejs_kino", "Kino klasyki: Rejs (pokaz specjalny)", Category.CINEMA, ["kino", "stand-up"], 1, "20:00", 2, "pod_baranami", 22,
     "Kultowa komedia na dużym ekranie + krótkie wprowadzenie filmoznawcy."),
    ("e_planszowki", "Wieczór planszówek dla nowych w mieście", Category.MEETUP, ["planszówki"], 1, "18:00", 4, "hevre", 0,
     "Przynieś ulubioną grę albo skorzystaj z naszej półki. Idealne na poznanie ludzi."),
    ("e_filharmonia", "Wieczór symfoniczny: Beethoven i Dvořák", Category.MUSIC, ["klasyka"], 2, "19:00", 2, "filharmonia", 60,
     "VII Symfonia Beethovena i Symfonia 'Z Nowego Świata' Dvořáka."),
    ("e_mnk_oprowadzanie", "Oprowadzanie kuratorskie: Wyspiański", Category.EXHIBITION, ["historia", "sztuka współczesna"], 2, "17:00", 1.5, "mnk", 30,
     "Witraże, pastele i projekty teatralne w opowieści kuratorki."),
    ("e_joga_jordana", "Poranna joga w Parku Jordana", Category.SPORT, ["joga", "natura"], 2, "08:00", 1, "jordana", 0,
     "Łagodna praktyka dla każdego poziomu. Weź matę i ciepłą bluzę."),
    ("e_food_tour", "Street food tour: Kazimierz", Category.FOOD, ["street food", "gotowanie"], 2, "18:00", 2.5, "plac_nowy", 45,
     "Zapiekanki z Okrąglaka, pierogi i bajgle — 5 przystanków, 1 przewodnik."),
    ("e_studio_indie", "Koncert polskiej sceny indie", Category.MUSIC, ["indie", "rock"], 3, "20:00", 3, "studio", 70,
     "Trzy zespoły, jeden wieczór — przegląd najciekawszych debiutów roku."),
    ("e_fotospacer", "Fotospacer po Kazimierzu", Category.OUTDOOR, ["fotografia", "spacery", "architektura"], 3, "16:00", 2.5, "plac_nowy", 0,
     "Złota godzina, podwórka i neony. Wystarczy telefon."),
    ("e_python_meetup", "Meetup pythonowy: AI w praktyce", Category.MEETUP, ["python", "technologia"], 3, "18:00", 3, "agh", 0,
     "Dwa talki (LLM-y w produkcji, Streamlit w 15 minut) i networking przy pizzy."),
    ("e_slowacki_komedia", "Komedia omyłek w Teatrze Słowackiego", Category.THEATRE, ["teatr"], 4, "19:00", 2, "slowacki", 80,
     "Lekka, błyskotliwa komedia w jednym z najpiękniejszych teatrów w Polsce."),
    ("e_kopiec_zachod", "Zachód słońca na Kopcu Kościuszki", Category.OUTDOOR, ["spacery", "natura", "fotografia"], 4, "17:30", 2, "kopiec", 0,
     "Wspólne wejście i panorama Krakowa o zachodzie. Termos mile widziany."),
    ("e_language_exchange", "Language exchange: PL ⇄ EN ⇄ DE", Category.MEETUP, ["języki obce"], 4, "19:00", 3, "massolit", 0,
     "Rotacyjne stoliki językowe co 20 minut. Erasmusi i lokalsi razem."),
    ("e_forum_techno", "Nocny set techno nad Wisłą", Category.MUSIC, ["techno", "taniec"], 5, "22:00", 6, "forum", 40,
     "Lokalni DJ-e, industrialna przestrzeń, widok na Wisłę."),
    ("e_rower_wisla", "Rowerowa pętla wzdłuż Wisły", Category.SPORT, ["rower", "natura"], 5, "10:00", 3, "bulwary", 0,
     "Ok. 30 km spokojnym tempem do Tyńca i z powrotem."),
    ("e_ceramika", "Warsztaty ceramiki dla początkujących", Category.WORKSHOP, ["rękodzieło", "design"], 5, "12:00", 3, "zablocie", 120,
     "Toczenie na kole i szkliwienie. Wszystkie materiały na miejscu."),
    ("e_opera_carmen", "Carmen — Opera Krakowska", Category.MUSIC, ["opera", "klasyka"], 6, "18:30", 3, "opera", 90,
     "Namiętność, zazdrość i najsłynniejsze arie w historii opery."),
    ("e_schindler_noc", "Nocne zwiedzanie Fabryki Schindlera", Category.EXHIBITION, ["historia"], 6, "20:00", 2, "schindler", 35,
     "Wystawa 'Kraków — czas okupacji' po zmroku, z przewodnikiem."),
    ("e_standup", "Stand-up open mic", Category.OTHER, ["stand-up"], 6, "20:00", 2, "kwadrat", 30,
     "Nowe twarze krakowskiej sceny komediowej. 10 komików, 7 minut każdy."),
    ("e_cricoteka", "Kantor dziś — performans i rozmowa", Category.THEATRE, ["teatr", "sztuka współczesna"], 7, "18:00", 2, "cricoteka", 25,
     "Młodzi artyści odpowiadają na teatr śmierci Tadeusza Kantora."),
    ("e_nowa_huta", "Spacer architektoniczny po Nowej Hucie", Category.OUTDOOR, ["architektura", "historia", "spacery"], 7, "11:00", 3, "plac_centralny", 0,
     "Socrealizm, ogrody i kino Światowid — historia idealnego miasta."),
    ("e_kijow_qa", "Przedpremierowy pokaz + Q&A z reżyserką", Category.CINEMA, ["kino"], 8, "19:30", 2.5, "kijow", 28,
     "Polski dramat obyczajowy przed premierą, po seansie rozmowa z twórczynią."),
    ("e_startup_wieczor", "Wieczór startupowy: pitch & networking", Category.MEETUP, ["startupy", "technologia"], 8, "18:30", 3, "ice", 0,
     "5 pitchy, jury z funduszy VC i dużo rozmów kuluarowych."),
    ("e_degustacja_win", "Degustacja polskich win", Category.FOOD, ["wino"], 8, "19:00", 2, "winiarnia", 90,
     "Sześć win z Małopolski i Podkarpacia z komentarzem sommeliera."),
    ("e_tauron_rock", "Rockowa noc: legendy lat 90.", Category.MUSIC, ["rock"], 9, "19:30", 3, "tauron", 150,
     "Największe przeboje dekady na żywo, z pełną produkcją świateł."),
    ("e_ogrod_lema", "Eksperymenty w Ogrodzie Doświadczeń", Category.WORKSHOP, ["nauka", "natura"], 9, "11:00", 3, "ogrod_lema", 15,
     "Fizyka na świeżym powietrzu: wahadła, pryzmaty i akustyka."),
    ("e_mecz", "Mecz ligowy — wspólne kibicowanie", Category.SPORT, ["piłka nożna"], 9, "18:00", 2, "stadion", 50,
     "Idziemy razem na trybunę rodzinną. Szaliki obowiązkowe."),
    ("e_manggha_anime", "Wieczór anime w Manggha", Category.CINEMA, ["kino", "gry wideo"], 10, "18:00", 3, "manggha", 20,
     "Podwójny seans klasyki japońskiej animacji z prelekcją."),
    ("e_foto_nocna", "Warsztaty fotografii nocnej", Category.WORKSHOP, ["fotografia"], 10, "19:00", 2.5, "bulwary", 50,
     "Długie czasy naświetlania, statyw i światła miasta nad Wisłą."),
    ("e_lotnictwo_noc", "Muzeum Lotnictwa: nocne zwiedzanie hangarów", Category.EXHIBITION, ["historia", "technologia"], 11, "19:00", 2, "lotnictwo", 25,
     "Samoloty i silniki w scenicznym świetle, z opowieściami pilotów."),
    ("e_cupping_kawa", "Cupping kawowy — 5 krajów, 5 ziaren", Category.FOOD, ["kawa"], 11, "11:00", 2, "palarnia", 35,
     "Profesjonalna degustacja kaw speciality z palaczem."),
    ("e_festiwal_swiatla", "Festiwal Światła na Rynku", Category.FESTIVAL, ["sztuka współczesna", "fotografia"], 12, "18:00", 5, "rynek", 0,
     "Mappingi na Sukiennicach i instalacje świetlne w całym Starym Mieście."),
    ("e_festiwal_literacki", "Festiwal literacki — spotkania autorskie", Category.FESTIVAL, ["literatura"], 13, "10:00", 8, "ice", 0,
     "Cały dzień spotkań, podpisywania książek i paneli o literaturze."),
]

# (id, imię, bio, tagi, numer avatara na pravatar.cc)
_USER_ROWS: list[tuple] = [
    ("u_ola", "Ola", "Od miesiąca w Krakowie, szukam ekipy na koncerty i wystawy.",
     ["jazz", "sztuka współczesna", "kino", "kawa", "fotografia"], 47),
    ("u_kuba", "Kuba", "Gitarzysta-amator, planszówkowy nerd, zawsze na jam session.",
     ["jazz", "rock", "planszówki", "stand-up", "technologia"], 12),
    ("u_marta", "Marta", "Polonistka. Teatr, dobra książka i kieliszek wina.",
     ["teatr", "literatura", "kino", "wino", "spacery"], 45),
    ("u_piotr", "Piotr", "Backend dev, rano biegam, wieczorem meetupy.",
     ["bieganie", "rower", "natura", "technologia", "python"], 15),
    ("u_zosia", "Zosia", "Fotografka i tancerka. Noc należy do techno.",
     ["techno", "taniec", "fotografia", "design", "street food"], 32),
    ("u_michal", "Michał", "Founder w early-stage startupie, gracz, fan sci-fi.",
     ["python", "startupy", "technologia", "gry wideo", "planszówki"], 53),
    ("u_ania", "Ania", "Przewodniczka po Krakowie. Opera, historia i architektura.",
     ["klasyka", "opera", "historia", "architektura", "kawa"], 44),
    ("u_tomek", "Tomek", "Śmieję się głośno w kinie i na stand-upach.",
     ["stand-up", "kino", "rock", "street food", "piłka nożna"], 59),
    ("u_julia", "Julia", "Joga o świcie, góry w weekend, uczę się hiszpańskiego.",
     ["joga", "natura", "spacery", "gotowanie", "języki obce"], 26),
    ("u_bartek", "Bartek", "Architekt. Fotografuję miasto, słucham jazzu na winylach.",
     ["jazz", "klasyka", "fotografia", "architektura", "wino"], 68),
    ("u_natalia", "Natalia", "Kuratorka i projektantka. Galerie, indie i teatr alternatywny.",
     ["sztuka współczesna", "design", "fotografia", "teatr", "indie"], 20),
    ("u_lukas", "Lukas", "Erasmus z Lipska 🇩🇪 Learning Polish, love techno & history.",
     ["języki obce", "techno", "street food", "historia", "bieganie"], 33),
]

# event_id -> lista user_id (z prefiksem "!" = open_to_meet=False)
_ATTENDANCE: dict[str, list[str]] = {
    "e_jazz_alchemia": ["u_ola", "u_kuba", "u_bartek", "u_natalia", "u_tomek"],
    "e_wawel_legendy": ["u_lukas", "u_julia"],
    "e_mocak_wystawa": ["u_ola", "u_natalia", "u_zosia", "u_bartek"],
    "e_stary_wesele": ["u_marta", "u_natalia", "u_ola"],
    "e_rejs_kino": ["u_tomek", "u_marta", "u_ola", "u_kuba"],
    "e_planszowki": ["u_kuba", "u_michal", "u_lukas", "u_ola"],
    "e_filharmonia": ["u_ania", "u_bartek", "u_marta"],
    "e_mnk_oprowadzanie": ["u_ania", "u_bartek", "u_marta"],
    "e_joga_jordana": ["u_julia"],
    "e_food_tour": ["u_zosia", "u_lukas", "u_tomek"],
    "e_studio_indie": ["u_natalia", "u_tomek", "u_kuba"],
    "e_fotospacer": ["u_ola", "u_bartek", "u_zosia", "u_natalia"],
    "e_python_meetup": ["u_michal", "u_piotr", "u_kuba"],
    "e_slowacki_komedia": ["u_marta", "u_ania"],
    "e_kopiec_zachod": ["u_julia", "u_piotr", "u_ola"],
    "e_language_exchange": ["u_lukas", "u_julia", "u_ola"],
    "e_forum_techno": ["u_zosia", "u_lukas", "u_natalia"],
    "e_rower_wisla": ["u_piotr", "u_julia"],
    "e_ceramika": ["u_zosia", "u_julia"],
    "e_opera_carmen": ["u_ania", "u_bartek", "u_ola"],
    "e_schindler_noc": ["u_lukas", "u_ania"],
    "e_standup": ["u_tomek", "u_kuba"],
    "e_cricoteka": ["u_natalia", "u_marta", "u_ola"],
    "e_nowa_huta": ["u_ania", "u_bartek", "u_lukas"],
    "e_kijow_qa": ["!u_marta", "u_tomek"],
    "e_startup_wieczor": ["u_michal", "u_piotr"],
    "e_degustacja_win": ["u_marta", "u_bartek"],
    "e_tauron_rock": ["u_kuba", "u_tomek"],
    "e_ogrod_lema": ["u_piotr", "u_michal"],
    "e_mecz": ["u_tomek"],
    "e_manggha_anime": ["u_michal", "u_zosia", "u_lukas"],
    "e_foto_nocna": ["u_bartek", "u_ola"],
    "e_lotnictwo_noc": ["u_michal", "u_piotr"],
    "e_cupping_kawa": ["u_ola", "u_ania"],
    "e_festiwal_swiatla": ["u_zosia", "u_natalia", "u_ola", "u_michal"],
    "e_festiwal_literacki": ["u_marta"],
}

# (event_id, user_id, minut_temu, tekst)
_MESSAGES: list[tuple] = [
    ("e_jazz_alchemia", "u_kuba", 95, "Ktoś idzie od początku? Będę ok. 19:50 przy barze 🎷"),
    ("e_jazz_alchemia", "u_bartek", 80, "Ja dołączę koło 20:30, biorę aparat."),
    ("e_jazz_alchemia", "u_natalia", 42, "Super, to do zobaczenia! Zajmijcie stolik przy scenie 🙏"),
    ("e_planszowki", "u_michal", 300, "Biorę Azul i Wsiąść do Pociągu."),
    ("e_planszowki", "u_lukas", 240, "I can bring Codenames (English version) 🙂"),
    ("e_fotospacer", "u_zosia", 600, "Zbiórka przy Okrąglaku? Złota godzina jest ok. 16:30."),
]


@dataclass
class MockDataset:
    events: list[Event] = field(default_factory=list)
    users: list[User] = field(default_factory=list)
    attendance: list[Attendance] = field(default_factory=list)
    messages: list[ChatMessage] = field(default_factory=list)


def _at(today: date, day_offset: int, hhmm: str) -> datetime:
    hours, minutes = map(int, hhmm.split(":"))
    return datetime.combine(today + timedelta(days=day_offset), time(hours, minutes))


def build_mock_dataset(today: date | None = None, reference_now: datetime | None = None) -> MockDataset:
    today = today or date.today()
    reference_now = reference_now or datetime.now().replace(microsecond=0)

    events: list[Event] = []
    for ev_id, title, cat, tags, day, hhmm, hours, venue_key, price, desc in _EVENT_ROWS:
        venue = KRAKOW_VENUES[venue_key]
        start = _at(today, day, hhmm)
        events.append(Event(
            id=ev_id, title=title, description=desc, category=cat, tags=tags,
            start=start, end=start + timedelta(hours=hours),
            venue=venue.name, address=f"{venue.address}, Kraków", lat=venue.lat, lon=venue.lon,
            price_pln=float(price), source="mock",
        ))

    users = [
        User(id=uid, name=name, bio=bio, tags=tags,
             avatar_url=f"https://i.pravatar.cc/150?img={img}",
             created_at=reference_now - timedelta(days=30))
        for uid, name, bio, tags, img in _USER_ROWS
    ]

    attendance: list[Attendance] = []
    for event_id, user_ids in _ATTENDANCE.items():
        for i, raw in enumerate(user_ids):
            attendance.append(Attendance(
                user_id=raw.lstrip("!"), event_id=event_id, status=AttendanceStatus.GOING,
                open_to_meet=not raw.startswith("!"),
                created_at=reference_now - timedelta(hours=48 - i),
            ))

    messages = [
        ChatMessage(id=f"msg_seed_{i:03d}", room_id=event_room_id(event_id), user_id=user_id, text=text,
                    created_at=reference_now - timedelta(minutes=minutes_ago))
        for i, (event_id, user_id, minutes_ago, text) in enumerate(_MESSAGES)
    ]

    return MockDataset(events=events, users=users, attendance=attendance, messages=messages)


if __name__ == "__main__":
    ds = build_mock_dataset()
    print(f"events={len(ds.events)} users={len(ds.users)} "
          f"attendance={len(ds.attendance)} messages={len(ds.messages)}")
