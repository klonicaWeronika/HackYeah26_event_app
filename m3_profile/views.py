"""
M3 — profil użytkownika: awatar, karta osoby, edycja i podgląd profilu, przełącznik użytkownika.

SZKIELET (walking skeleton): działa na mockach od godziny 0.
Zakres do zrobienia: m3_profile/TASK_SPEC.md
"""

from __future__ import annotations

import html
import re
import zlib
from urllib.parse import quote

import streamlit as st

from m3_profile.avatar import AvatarError, avatar_from_upload  # re-eksport: publiczne API M3 (TASK_SPEC §3.2)
from m3_profile.personas import persona_scenario, sort_for_switcher, switcher_labels
from m3_profile.privacy import set_visibility_everywhere, visibility_summary
from m3_profile.profile_data import profile_overlap
from m3_profile.validation import BIO_MAX, NAME_MAX, TAGS_MAX, TAGS_MIN, validate_profile
from shared import state
from shared.config import DEFAULT_USER_ID, FEATURES
from shared.formatting import format_when
from shared.models import INTEREST_TAGS, Event, MatchResult, User, new_id
from shared.storage import Storage
from shared.state import View

_AVATAR_COLORS = ["#E4572E", "#17BEBB", "#FFC914", "#2E282A", "#76B041", "#7E5BEF", "#F46197"]
_MD_SPECIAL = set("\\`*_{}[]()#+-.!|<>~$")


def _md_escape(text: str) -> str:
    """Dane użytkownika w markdownie (st.toast/st.markdown bez HTML): bez formatowania i linków."""
    return "".join(f"\\{c}" if c in _MD_SPECIAL else c for c in text)


_SAFE_DATA_URI = re.compile(r"^data:image/(?:jpeg|png|webp|gif);base64,[A-Za-z0-9+/=]+$")
_URL_SAFE_CHARS = ":/?#[]@!$&*+,;=%~-._"   # bez ' " ( ) \ i spacji -> URL nie wyjdzie z CSS url('…')


def _avatar_image_url(url: str | None) -> str | None:
    """URL zdjęcia bezpieczny do CSS `url('…')` albo None (-> same inicjały).

    Biała lista: http(s) oraz data:image/(jpeg|png|webp|gif);base64 (z avatar_from_upload).
    """
    url = (url or "").strip()
    if _SAFE_DATA_URI.match(url):
        return url
    if url.lower().startswith(("http://", "https://")):
        return quote(url, safe=_URL_SAFE_CHARS)
    return None


def _initials_text_color(background: str) -> str:
    """Biały albo grafitowy tekst inicjałów — ten, który ma lepszy kontrast z tłem."""
    r, g, b = (int(background[i:i + 2], 16) / 255 for i in (1, 3, 5))
    luminance = 0.2126 * r ** 2.2 + 0.7152 * g ** 2.2 + 0.0722 * b ** 2.2
    return "#1F1F1F" if luminance > 0.3 else "#FFFFFF"


def avatar_html(user: User, size: int = 40) -> str:
    """Okrągły awatar: inicjały zawsze pod spodem, zdjęcie (jeśli jest) jako warstwa na wierzchu.

    Bez JavaScriptu — Streamlit wycina `onerror` z <img>, więc zwykły <img> przy braku internetu
    albo złym URL pokazuje „zepsuty obrazek”. Tu zdjęcie jest TŁEM warstwy (`background-image`):
    gdy się nie wczyta, przeglądarka nic nie rysuje i widać inicjały. Dane użytkownika są escapowane.
    """
    color = _AVATAR_COLORS[zlib.crc32(user.id.encode()) % len(_AVATAR_COLORS)]
    photo = ""
    if src := _avatar_image_url(user.avatar_url):
        photo = (
            '<div style="position:absolute;top:0;left:0;width:100%;height:100%;border-radius:50%;'
            f"background:center/cover no-repeat url('{html.escape(src, quote=True)}');\"></div>"
        )
    return (
        f'<div aria-hidden="true" style="position:relative;overflow:hidden;width:{size}px;height:{size}px;'
        f"border-radius:50%;flex-shrink:0;background:{color};color:{_initials_text_color(color)};"
        f"display:flex;align-items:center;justify-content:center;font-weight:600;"
        f'font-size:{size * 0.4:.0f}px;">{html.escape(user.initials)}{photo}</div>'
    )


def render_avatar(user: User, size: int = 40, caption: str | None = None) -> None:
    label = f'<span style="font-weight:600;">{html.escape(caption)}</span>' if caption else ""
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;">{avatar_html(user, size)}{label}</div>',
        unsafe_allow_html=True,
    )


def render_user_switcher(storage: Storage, key: str = "m3_user_switch") -> None:
    """'Zaloguj jako…' (w MVP bez haseł) + „➕ Nowy profil” (onboarding, M3-04)."""
    _expire_onboarding_flag()
    users = sort_for_switcher(storage.list_users())       # persony demo w kolejności scenariusza (M3-09)
    ids = [u.id for u in users]
    names = {u.id: u.name for u in users}
    labels = switcher_labels(users)                       # unikalne: selectbox szuka wyboru po etykiecie
    current = state.current_user_id()

    if ids and current not in ids:
        # ?user= z linku nie istnieje (literówka, profil skasowany „Resetem demo”) -> fallback jak w app.py
        fallback = DEFAULT_USER_ID if DEFAULT_USER_ID in ids else ids[0]
        state.set_current_user(fallback)                    # poprawia też ?user= w URL
        st.toast(f"Nie znaleziono profilu z linku — jesteś teraz: {_md_escape(names[fallback])}.")
        current = fallback

    def _on_change() -> None:
        state.set_current_user(st.session_state[key])
        state.select_event(None)
        _cancel_onboarding()

    if ids:
        # Synchronizacja PRZED utworzeniem widgetu: użytkownik mógł się zmienić poza przełącznikiem
        # (onboarding, ?user= w URL). Bez `index=` — wartość pochodzi wyłącznie z session_state.
        st.session_state[key] = current
        st.selectbox("Zaloguj jako", ids, format_func=labels.get, key=key, on_change=_on_change)
        if scenario := persona_scenario(current):
            st.caption(scenario)
    st.button("➕ Nowy profil", key=f"{key}_new", on_click=_start_onboarding, width="stretch",
              help="Załóż profil dla nowej osoby (zdjęcie, imię, zainteresowania).")


# --------------------------------------------------------------------------- #
# Karta osoby (M3-05): jeden blok HTML (stabilny w kolumnie ≈ 320 px) + akcje
# --------------------------------------------------------------------------- #

_CARD_MAX_CHIPS = 6
_CARD_TEXT_MAX = 90
_CHIP = "display:inline-block;padding:1px 8px;border-radius:999px;font-size:0.75rem;line-height:1.5;"
_CHIP_SHARED = _CHIP + (
    "background:rgba(228,87,46,0.16);border:1px solid rgba(228,87,46,0.55);font-weight:600;"
)
_CHIP_OTHER = _CHIP + "background:rgba(128,128,128,0.12);border:1px solid rgba(128,128,128,0.25);"


def _score_color(score: float) -> str:
    """Kolor badge'a/paska; każdy ma kontrast ≥ 4.5:1 z białym tekstem (WCAG AA)."""
    if score >= 0.5:
        return "#1E7B45"      # zielony — mocne dopasowanie
    if score >= 0.25:
        return "#A35F00"      # bursztyn — sporo wspólnego
    return "#5F6670"          # szary — mało wspólnego (ale idziecie na to samo)


def _shorten(text: str, limit: int = _CARD_TEXT_MAX) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _chip_html(tag: str, shared: bool) -> str:
    if shared:
        return f'<span style="{_CHIP_SHARED}" title="Wspólne zainteresowanie">✓ {html.escape(tag)}</span>'
    return f'<span style="{_CHIP_OTHER}">{html.escape(tag)}</span>'


def user_card_html(user: User, match: MatchResult | None = None) -> str:
    """HTML karty: awatar, imię, wynik (procent + pasek), uzasadnienie/bio, tagi (wspólne wyróżnione).

    Czysty string (bez wywołań Streamlit) — wszystkie dane użytkownika i M4 przechodzą przez html.escape.
    Bez wcięć i nowych linii: markdown potraktowałby wcięty HTML jako blok kodu.
    """
    name_style = "font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
    head = f'<span style="{name_style}">{html.escape(user.name)}</span>'
    bar = ""
    if match is not None:
        pct, color = round(match.score * 100), _score_color(match.score)
        head += (
            f'<span title="Dopasowanie zainteresowań: {pct}%" style="flex-shrink:0;font-size:0.8rem;'
            f'font-weight:700;color:#fff;background:{color};border-radius:999px;padding:0 8px;">{pct}%</span>'
        )
        bar = (
            f'<div role="img" aria-label="Dopasowanie {pct}%" style="height:5px;border-radius:3px;'
            f'background:rgba(128,128,128,0.2);margin:4px 0 2px;"><div style="width:{max(pct, 3)}%;'
            f'height:100%;border-radius:3px;background:{color};"></div></div>'
        )
    text = match.reason if match and match.reason else user.bio
    text_html = (
        f'<div style="font-size:0.85rem;opacity:0.8;margin:2px 0 6px;">{html.escape(_shorten(text))}</div>'
        if text else ""
    )
    shared = list(match.shared_tags) if match else []
    tags = [(t, True) for t in shared] + [(t, False) for t in user.tags if t not in shared]
    chips = "".join(_chip_html(t, is_shared) for t, is_shared in tags[:_CARD_MAX_CHIPS])
    if len(tags) > _CARD_MAX_CHIPS:
        chips += f'<span style="{_CHIP_OTHER}">+{len(tags) - _CARD_MAX_CHIPS}</span>'
    chips_html = f'<div style="display:flex;flex-wrap:wrap;gap:4px;">{chips}</div>' if chips else ""
    return (
        '<div style="display:flex;gap:10px;align-items:flex-start;">'
        f"{avatar_html(user, 44)}"
        '<div style="flex:1;min-width:0;">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;gap:6px;">{head}</div>'
        f"{bar}{text_html}{chips_html}"
        "</div></div>"
    )


def _dm_callback():
    """`open_dm` z M5, jeśli DM jest włączony i już dostarczony; inaczej None (przycisk się nie pokazuje).

    Import leniwy: M5 importuje z M3 (avatar_html), więc import na górze modułu dałby cykl.
    """
    if not FEATURES.get("dm_chat"):
        return None
    try:
        from m5_chat import chat_view
    except ImportError:
        return None
    return chat_view.open_dm if hasattr(chat_view, "open_dm") else None


def _team_api():
    """Moduł grup M5 (`open_event_chat` + `team_action_label`) albo None, gdy M5 go nie dostarcza.

    Import leniwy, jak w `_dm_callback`.
    """
    try:
        from m5_chat import group_view
    except ImportError:
        return None
    has_api = hasattr(group_view, "open_event_chat") and hasattr(group_view, "team_action_label")
    return group_view if has_api else None


def render_user_card(user: User, match: MatchResult | None = None, *, key: str) -> None:
    """Karta osoby (dopasowania w prawym panelu, listy uczestników).

    Przy dopasowaniu do wydarzenia (`match.event_id`) „Dodaj do ekipy” zaprasza do mojej grupy na to
    wydarzenie i otwiera jej czat (M5; etykieta wg stanu: „Czat ekipy”, „Zaproszono”, „Zaproszenie”);
    bez kontekstu wydarzenia — „Napisz”, prywatny czat 1:1 (DM).
    `key` musi być unikalny na stronie — przyciski dostają klucze `{key}_profile`, `{key}_group` i `{key}_dm`.
    """
    with st.container(border=True):
        st.markdown(user_card_html(user, match), unsafe_allow_html=True)
        actions: list[tuple[str, dict]] = []
        if FEATURES["profile_view"]:
            actions.append(("👤 Profil", dict(
                key=f"{key}_profile", on_click=state.go_to,
                args=(View.PROFILE_VIEW,), kwargs={"user_id": user.id},
            )))
        open_dm, team = _dm_callback(), _team_api()
        me = state.current_user_id()
        if user.id != me and match is not None and match.event_id and team is not None:
            actions.append((team.team_action_label(me, user.id, match.event_id), dict(
                key=f"{key}_group", on_click=team.open_event_chat, args=(me, user.id, match.event_id),
                help="Twoja ekipa na to wydarzenie — otworzy się czat grupy.",
            )))
        elif user.id != me and open_dm is not None:
            actions.append(("💬 Napisz", dict(key=f"{key}_dm", on_click=open_dm, args=(me, user.id))))
        if actions:
            # Kolumny proporcjonalne do etykiet: „➕ Dodaj do ekipy” mieści się obok „👤 Profil” bez ucinania.
            widths = [max(len(label), 8) for label, _ in actions]
            for col, (label, params) in zip(st.columns(widths), actions):
                col.button(label, width="stretch", **params)


# --------------------------------------------------------------------------- #
# Zdjęcie profilowe (M3-02): uploader POZA st.form + szkic w session_state
# --------------------------------------------------------------------------- #

_AVATAR_DRAFT = "m3_avatar_draft"     # {"user_id", "avatar_url": str | None} — niezapisana zmiana zdjęcia
_AVATAR_ERROR = "m3_avatar_error"     # {"user_id": str, "message": str} — komunikat AvatarError do st.error
_AVATAR_NONCE = "m3_avatar_nonce"     # zmiana klucza = pusty uploader (wartości uploadera nie da się ustawić)
_UPLOAD_TYPES = ["jpg", "jpeg", "png", "webp"]


def _avatar_draft(user_id: str) -> dict | None:
    draft = st.session_state.get(_AVATAR_DRAFT)
    return draft if draft and draft["user_id"] == user_id else None


def _pending_avatar_url(user: User) -> str | None:
    """Zdjęcie, które zostanie zapisane: szkic (nowe / usunięte), a bez szkicu — obecne."""
    draft = _avatar_draft(user.id)
    return draft["avatar_url"] if draft else user.avatar_url


def _discard_avatar_draft() -> None:
    st.session_state.pop(_AVATAR_DRAFT, None)
    st.session_state.pop(_AVATAR_ERROR, None)
    st.session_state[_AVATAR_NONCE] = st.session_state.get(_AVATAR_NONCE, 0) + 1


def _on_avatar_upload(user_id: str, uploader_key: str) -> None:
    """Callback uploadera: przetwarza plik RAZ (nie przy każdym rerunie) i odkłada szkic."""
    st.session_state.pop(_AVATAR_ERROR, None)
    uploaded = st.session_state.get(uploader_key)
    if uploaded is None:                                   # „✕” w uploaderze = cofnij szkic
        st.session_state.pop(_AVATAR_DRAFT, None)
        return
    try:
        data_uri = avatar_from_upload(uploaded.getvalue())
    except AvatarError as exc:
        st.session_state[_AVATAR_ERROR] = {"user_id": user_id, "message": str(exc)}
        return
    st.session_state[_AVATAR_DRAFT] = {"user_id": user_id, "avatar_url": data_uri}


def _on_avatar_remove(user_id: str) -> None:
    _discard_avatar_draft()
    st.session_state[_AVATAR_DRAFT] = {"user_id": user_id, "avatar_url": None}


def _render_avatar_picker(user: User) -> None:
    """Podgląd awatara (ze szkicem) + wybór pliku. Zmiana trafia do bazy dopiero po „Zapisz”."""
    pending_url = _pending_avatar_url(user)
    col_preview, col_upload = st.columns([1, 3], vertical_alignment="center")
    with col_preview:
        st.markdown(avatar_html(user.copy_with(avatar_url=pending_url), 96), unsafe_allow_html=True)
        if _avatar_draft(user.id):
            st.caption("Podgląd — kliknij „Zapisz”, aby zastosować.")
    with col_upload:
        uploader_key = f"m3_avatar_upload_{user.id}_{st.session_state.get(_AVATAR_NONCE, 0)}"
        st.file_uploader(
            "Zdjęcie profilowe (JPG, PNG lub WEBP, maks. 5 MB)", type=_UPLOAD_TYPES, key=uploader_key,
            on_change=_on_avatar_upload, args=(user.id, uploader_key),
            help="Kadrujemy do kwadratu i zmniejszamy do 256×256 px. Metadane zdjęcia (np. GPS) są usuwane.",
        )
        error = st.session_state.get(_AVATAR_ERROR)
        if error and error["user_id"] == user.id:
            st.error(error["message"])
        if pending_url:
            st.button("🗑️ Usuń zdjęcie", key=f"m3_avatar_remove_{user.id}", type="tertiary",
                      on_click=_on_avatar_remove, args=(user.id,))


# --------------------------------------------------------------------------- #
# Edycja profilu (M3-03): walidacja z komunikatami przy polach, zapis w callbacku
# --------------------------------------------------------------------------- #

_PE_ERRORS = "m3_pe_errors"           # {"user_id": str, "errors": {pole: komunikat}} po nieudanym „Zapisz”


def _pe_key(field: str, user_id: str) -> str:
    """Klucze pól edytora: m3_pe_name_<id>, m3_pe_bio_<id>, m3_pe_tags_<id>."""
    return f"m3_pe_{field}_{user_id}"


def _field_errors(user_id: str) -> dict[str, str]:
    saved = st.session_state.get(_PE_ERRORS)
    return saved["errors"] if saved and saved["user_id"] == user_id else {}


def _render_profile_fields(storage: Storage, *, key_id: str, name: str, bio: str, tags: list[str]) -> None:
    """Imię, bio i zainteresowania z komunikatem błędu pod każdym polem (do użycia w st.form)."""
    errors = _field_errors(key_id)
    st.text_input("Imię / nick", value=name, max_chars=NAME_MAX, key=_pe_key("name", key_id),
                  placeholder="np. Ola")
    if "name" in errors:
        st.error(errors["name"], icon="⚠️")
    st.text_area("Kilka słów o sobie (opcjonalnie)", value=bio, max_chars=BIO_MAX, key=_pe_key("bio", key_id),
                 placeholder="np. Od miesiąca w Krakowie, szukam ekipy na koncerty i wystawy.")
    if "bio" in errors:
        st.error(errors["bio"], icon="⚠️")
    options = sorted(set(INTEREST_TAGS) | set(storage.known_tags()) | set(tags))
    st.multiselect(
        f"Zainteresowania ({TAGS_MIN}–{TAGS_MAX})", options, default=tags, accept_new_options=True,
        key=_pe_key("tags", key_id), placeholder="Wybierz z listy albo wpisz własne…",
        help="Na ich podstawie dobieramy osoby i wydarzenia. Własne zainteresowanie: wpisz i naciśnij Enter.",
    )
    if "tags" in errors:
        st.error(errors["tags"], icon="⚠️")


def _validated_fields(key_id: str) -> tuple[dict, dict[str, str]]:
    """Czyta pola formularza z session_state i waliduje; błędy odkłada do pokazania przy polach."""
    ss = st.session_state
    clean, errors = validate_profile(
        ss.get(_pe_key("name", key_id), ""),
        ss.get(_pe_key("bio", key_id), ""),
        ss.get(_pe_key("tags", key_id), []),
    )
    if errors:
        ss[_PE_ERRORS] = {"user_id": key_id, "errors": errors}
    else:
        ss.pop(_PE_ERRORS, None)
    return clean, errors


def _on_save_profile(storage: Storage, user_id: str) -> None:
    """„Zapisz” (on_click): walidacja -> zapis -> toast + mapa w jednym rerunie. Błąd = zostajemy."""
    clean, errors = _validated_fields(user_id)
    if errors:
        return
    user = storage.get_user(user_id)
    if user is None:                                       # np. „Reset danych demo” w innej karcie
        errors = {"name": "Ten profil już nie istnieje."}
        st.session_state[_PE_ERRORS] = {"user_id": user_id, "errors": errors}
        return
    storage.upsert_user(user.copy_with(**clean, avatar_url=_pending_avatar_url(user)))
    _discard_avatar_draft()
    st.toast("Profil zapisany ✅")
    state.go_to(View.MAP)


def _leave_editor() -> None:
    _discard_avatar_draft()
    st.session_state.pop(_PE_ERRORS, None)
    state.go_to(View.MAP)


def render_profile_editor(storage: Storage, user: User) -> None:
    """Edycja własnego profilu: zdjęcie (upload -> data URI), imię, bio, zainteresowania.

    Po „➕ Nowy profil” (flaga `m3_onboarding`) ten sam widok pokazuje onboarding — app.py bez zmian.
    """
    if st.session_state.get(_ONBOARDING):
        render_onboarding(storage)
        return
    st.subheader("✏️ Twój profil")
    _render_avatar_picker(user)

    with st.form(f"m3_pe_form_{user.id}"):
        _render_profile_fields(storage, key_id=user.id, name=user.name, bio=user.bio, tags=user.tags)
        st.form_submit_button("Zapisz", type="primary", on_click=_on_save_profile, args=(storage, user.id))

    _render_visibility_settings(storage, user)
    st.button("← Wróć do mapy", key="m3_back_from_editor", on_click=_leave_editor)


# --------------------------------------------------------------------------- #
# Prywatność (M3-08, wariant „tylko M3”): zbiorczo ukryj / pokaż w dopasowaniach
# --------------------------------------------------------------------------- #

def _on_set_visibility(storage: Storage, user_id: str, visible: bool) -> None:
    set_visibility_everywhere(storage, user_id, visible)
    # Przełącznik M5 w prawym panelu trzyma starą wartość w stanie widgetu i przy rerunie zapisałby ją
    # z powrotem do bazy (cofnąłby zmianę dla otwartego wydarzenia). Zamykamy panel -> widget znika,
    # a po ponownym otwarciu wydarzenia przełącznik czyta już nową wartość z bazy.
    if any(a.event_id == state.selected_event_id() for a in storage.list_user_attendance(user_id)):
        state.select_event(None)
    st.toast("👀 Znów widać Cię w dopasowaniach." if visible
             else "🙈 Ukryto Cię we wszystkich dopasowaniach.")


def _render_visibility_settings(storage: Storage, user: User) -> None:
    """Działa od razu na wszystkie zapisy (M4 już pomija open_to_meet=False). Szczegóły: privacy.py."""
    summary = visibility_summary(storage, user.id)
    with st.container(border=True):
        st.markdown("**🙈 Widoczność w dopasowaniach**")
        if summary.total:
            st.caption(f"Widać Cię w {summary.visible} z {summary.total} nadchodzących wydarzeń. "
                       "Pojedyncze wydarzenie ustawisz przełącznikiem przy nim.")
        else:
            st.caption("Nie masz jeszcze zapisów na nadchodzące wydarzenia.")
        col_hide, col_show = st.columns(2)
        col_hide.button("🙈 Ukryj mnie wszędzie", key="m3_priv_hide", width="stretch",
                        disabled=summary.visible == 0,
                        on_click=_on_set_visibility, args=(storage, user.id, False))
        col_show.button("👀 Pokaż mnie wszędzie", key="m3_priv_show", width="stretch",
                        disabled=summary.hidden == 0,
                        on_click=_on_set_visibility, args=(storage, user.id, True))
        st.caption("Przy nowym „Idę!” domyślnie będzie Cię widać — "
                   "zmienisz to przełącznikiem przy wydarzeniu.")


# --------------------------------------------------------------------------- #
# Onboarding (M3-04): nowa osoba -> profil w 30 s -> ?user= w URL
# --------------------------------------------------------------------------- #

_ONBOARDING = "m3_onboarding"                  # True = w widoku PROFILE_EDIT pokazujemy onboarding
_ONBOARDING_CREATED = "m3_onboarding_created"  # id utworzonej osoby (wynik render_onboarding po zapisie)
_NEW_KEY = "new"                               # sufiks kluczy formularza (m3_pe_name_new, …) i szkicu zdjęcia


def _start_onboarding() -> None:
    _discard_avatar_draft()
    st.session_state.pop(_PE_ERRORS, None)
    st.session_state.pop(_ONBOARDING_CREATED, None)
    st.session_state[_ONBOARDING] = True
    state.go_to(View.PROFILE_EDIT)


def _cancel_onboarding() -> None:
    if st.session_state.pop(_ONBOARDING, None):
        _discard_avatar_draft()
        st.session_state.pop(_PE_ERRORS, None)


def _expire_onboarding_flag() -> None:
    """Wyjście z onboardingu „bokiem” (np. przycisk czatu) -> następne „Edytuj profil” to zwykła edycja."""
    if st.session_state.get(_ONBOARDING) and state.current_view() is not View.PROFILE_EDIT:
        _cancel_onboarding()


def _leave_onboarding() -> None:
    _cancel_onboarding()
    state.go_to(View.MAP)


def _on_create_profile(storage: Storage) -> None:
    """„Utwórz profil” (on_click): walidacja jak w edycji -> nowy User -> zalogowanie (+ ?user=) -> mapa."""
    clean, errors = _validated_fields(_NEW_KEY)
    if errors:
        return
    user = User(id=new_id("u"), **clean, avatar_url=_pending_avatar_url(_onboarding_placeholder()))
    storage.upsert_user(user)
    state.set_current_user(user.id)            # ?user=<id> w URL -> profil przetrwa odświeżenie strony
    _cancel_onboarding()
    st.session_state[_ONBOARDING_CREATED] = user.id
    # Wybrany event zostaje otwarty: nowa osoba od razu klika „Idę!” i widzi pasujące osoby.
    st.toast(f"Witaj, {_md_escape(user.name)}! 🎉 Kliknij pinezkę, a potem „Idę!”, "
             "żeby zobaczyć pasujące osoby.")
    state.go_to(View.MAP)


def _onboarding_placeholder() -> User:
    """Tymczasowa „osoba” do podglądu awatara i szkicu zdjęcia przed utworzeniem profilu."""
    return User(id=_NEW_KEY, name="?")


def render_onboarding(storage: Storage) -> User | None:
    """Ekran powitalny „Utwórz profil”.

    Zwraca None, dopóki formularz jest na ekranie. Profil powstaje w callbacku „Utwórz profil”
    (osoba zostaje zalogowana, a widok wraca do mapy); jeśli ktoś wywoła tę funkcję w przebiegu
    tuż po zapisie, dostanie utworzonego `User` (jednorazowo) i nic nie zostanie narysowane.
    """
    created_id = st.session_state.pop(_ONBOARDING_CREATED, None)
    if created_id:
        return storage.get_user(created_id)

    st.subheader("👋 Cześć! Załóż profil w 30 sekund")
    st.caption(
        "1️⃣ Zdjęcie, imię i 3 zainteresowania → 2️⃣ „Idę!” przy wydarzeniu na mapie "
        "→ 3️⃣ zobaczysz osoby, które też idą i lubią to co Ty."
    )
    _render_avatar_picker(_onboarding_placeholder())
    with st.form("m3_onboarding_form"):
        _render_profile_fields(storage, key_id=_NEW_KEY, name="", bio="", tags=[])
        st.form_submit_button("Utwórz profil", type="primary", on_click=_on_create_profile, args=(storage,))
    st.button("← Wróć", key="m3_back_from_onboarding", on_click=_leave_onboarding,
              help="Wróć do mapy bez zakładania profilu.")
    return None


# --------------------------------------------------------------------------- #
# Podgląd profilu (M3-06): co mamy wspólnego + przyszłe wydarzenia + „Napisz”
# --------------------------------------------------------------------------- #

_PV_MAX_EVENTS = 8


def _plural(n: int, one: str, few: str, many: str) -> str:
    """Polska odmiana: 1 wydarzenie, 2–4 wydarzenia, 5+ wydarzeń (12–14 też „many”)."""
    if n == 1:
        return f"{n} {one}"
    return f"{n} {few if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else many}"


def _profile_header_html(user: User, subtitle: str) -> str:
    """Awatar 96 px + imię + podtytuł + bio. Nowe linie bio -> <br> (pusta linia zamknęłaby blok HTML)."""
    bio = html.escape(user.bio).replace("\n", "<br>")
    bio_html = f'<div style="margin-top:6px;">{bio}</div>' if bio else ""
    return (
        '<div style="display:flex;gap:16px;align-items:center;margin:8px 0 4px;">'
        f"{avatar_html(user, 96)}"
        '<div style="min-width:0;">'
        f'<div style="font-size:1.5rem;font-weight:700;line-height:1.2;">{html.escape(user.name)}</div>'
        f'<div style="opacity:0.7;font-size:0.9rem;">{html.escape(subtitle)}</div>'
        f"{bio_html}</div></div>"
    )


def _event_row_html(event: Event, *, hidden: bool = False) -> str:
    details = f"{format_when(event)} · {event.venue}"
    hidden_note = " · 🙈 ukryte w dopasowaniach" if hidden else ""
    return (
        f"{event.meta.emoji} <b>{html.escape(event.title)}</b><br>"
        f'<span style="opacity:0.7;font-size:0.85rem;">{html.escape(details)}{hidden_note}</span>'
    )


def _show_event_on_map(event_id: str) -> None:
    state.select_event(event_id)
    state.go_to(View.MAP)


def _render_event_rows(events: list[Event], hidden_ids: frozenset[str] = frozenset()) -> None:
    for event in events[:_PV_MAX_EVENTS]:
        col_text, col_button = st.columns([5, 1], vertical_alignment="center")
        col_text.markdown(_event_row_html(event, hidden=event.id in hidden_ids), unsafe_allow_html=True)
        col_button.button("Pokaż", key=f"m3_pv_show_{event.id}", type="tertiary",
                          on_click=_show_event_on_map, args=(event.id,),
                          help="Otwórz to wydarzenie w panelu obok mapy.")
    if len(events) > _PV_MAX_EVENTS:
        more = _plural(len(events) - _PV_MAX_EVENTS, "wydarzenie", "wydarzenia", "wydarzeń")
        st.caption(f"…i jeszcze {more}.")


def render_profile_view(storage: Storage, user: User) -> None:
    """Profil osoby (z karty w panelu): wspólne zainteresowania i wspólne PRZYSZŁE wydarzenia, „Napisz”.

    „← Wróć do mapy” nie zmienia wybranego wydarzenia — prawy panel zostaje otwarty.
    """
    viewer = storage.get_user(state.current_user_id())
    own = viewer is not None and viewer.id == user.id
    overlap = profile_overlap(storage, viewer, user)
    upcoming = len(overlap.common_events) + len(overlap.other_events)

    actions: list[tuple[str, dict]] = [("← Wróć do mapy", dict(
        key="m3_back_from_profile", on_click=state.go_to, args=(View.MAP,)))]
    if own:
        actions.append(("✏️ Edytuj profil", dict(key="m3_pv_edit", on_click=state.go_to,
                                                 args=(View.PROFILE_EDIT,))))
    elif (open_dm := _dm_callback()) is not None and viewer is not None:
        actions.append(("💬 Napisz", dict(key="m3_pv_dm", on_click=open_dm, args=(viewer.id, user.id),
                                          type="primary")))
    for col, (label, params) in zip(st.columns(len(actions) + 1)[: len(actions)], actions):
        col.button(label, width="stretch", **params)

    if own:
        subtitle = "To Twój profil — tak widzą Cię inni."
    else:
        parts = []
        if overlap.shared_tags:
            parts.append(_plural(len(overlap.shared_tags), "wspólne zainteresowanie",
                                 "wspólne zainteresowania", "wspólnych zainteresowań"))
        if overlap.common_events:
            parts.append(_plural(len(overlap.common_events), "wspólne wydarzenie", "wspólne wydarzenia",
                                 "wspólnych wydarzeń"))
        subtitle = "Macie " + " i ".join(parts) + "." if parts else "Zobacz, dokąd się wybiera."
    st.markdown(_profile_header_html(user, subtitle), unsafe_allow_html=True)

    st.markdown("#### Zainteresowania" if own else "#### 🤝 Wspólne zainteresowania")
    chips = [_chip_html(t, True) for t in overlap.shared_tags]
    chips += [_chip_html(t, False) for t in overlap.other_tags]
    if chips:
        st.markdown(f'<div style="display:flex;flex-wrap:wrap;gap:6px;">{"".join(chips)}</div>',
                    unsafe_allow_html=True)
    if not own and not overlap.shared_tags:
        st.caption("Brak wspólnych zainteresowań — może połączy Was wydarzenie?")

    if overlap.common_events:
        st.markdown("#### 📅 Wspólne wydarzenia")
        _render_event_rows(overlap.common_events)
    if overlap.other_events:
        st.markdown("#### Twoje nadchodzące wydarzenia" if own else
                    ("#### Wybiera się też na" if overlap.common_events else "#### Wybiera się na"))
        _render_event_rows(overlap.other_events, overlap.hidden_event_ids)
    if not upcoming:
        st.caption("Brak nadchodzących wydarzeń.")
