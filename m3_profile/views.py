"""
M3 — profil użytkownika: awatar, karta osoby, edycja i podgląd profilu, przełącznik użytkownika.

SZKIELET (walking skeleton): działa na mockach od godziny 0.
Zakres do zrobienia: m3_profile/TASK_SPEC.md
"""

from __future__ import annotations

import html
import zlib

import streamlit as st

from m3_profile.avatar import AvatarError, avatar_from_upload  # re-eksport: publiczne API M3 (TASK_SPEC §3.2)
from m3_profile.validation import BIO_MAX, NAME_MAX, TAGS_MAX, TAGS_MIN, validate_profile
from shared import state
from shared.config import DEFAULT_USER_ID, FEATURES
from shared.formatting import format_when
from shared.models import INTEREST_TAGS, MatchResult, User, new_id
from shared.storage import Storage
from shared.state import View

_AVATAR_COLORS = ["#E4572E", "#17BEBB", "#FFC914", "#2E282A", "#76B041", "#7E5BEF", "#F46197"]
_MD_SPECIAL = set("\\`*_{}[]()#+-.!|<>~$")


def _md_escape(text: str) -> str:
    """Dane użytkownika w markdownie (st.toast/st.markdown bez HTML): bez formatowania i linków."""
    return "".join(f"\\{c}" if c in _MD_SPECIAL else c for c in text)


def avatar_html(user: User, size: int = 40) -> str:
    """Okrągły awatar (zdjęcie albo inicjały). Bezpieczny: escapuje dane użytkownika."""
    style = f"width:{size}px;height:{size}px;border-radius:50%;flex-shrink:0;"
    if user.avatar_url:
        src = html.escape(user.avatar_url, quote=True)
        return f'<img src="{src}" alt="" style="{style}object-fit:cover;">'
    color = _AVATAR_COLORS[zlib.crc32(user.id.encode()) % len(_AVATAR_COLORS)]
    return (
        f'<div style="{style}background:{color};color:#fff;display:flex;align-items:center;'
        f'justify-content:center;font-weight:600;font-size:{size * 0.4:.0f}px;">'
        f"{html.escape(user.initials)}</div>"
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
    users = storage.list_users()
    ids = [u.id for u in users]
    names = {u.id: u.name for u in users}
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
        st.selectbox("Zaloguj jako", ids, format_func=names.get, key=key, on_change=_on_change)
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


def render_user_card(user: User, match: MatchResult | None = None, *, key: str) -> None:
    """Karta osoby (dopasowania w prawym panelu, listy uczestników).

    `key` musi być unikalny na stronie — przyciski dostają klucze `{key}_profile` i `{key}_dm`.
    """
    with st.container(border=True):
        st.markdown(user_card_html(user, match), unsafe_allow_html=True)
        actions: list[tuple[str, dict]] = []
        if FEATURES["profile_view"]:
            actions.append(("👤 Profil", dict(
                key=f"{key}_profile", on_click=state.go_to,
                args=(View.PROFILE_VIEW,), kwargs={"user_id": user.id},
            )))
        open_dm = _dm_callback()
        me = state.current_user_id()
        if open_dm is not None and user.id != me:
            actions.append(("💬 Napisz", dict(key=f"{key}_dm", on_click=open_dm, args=(me, user.id))))
        if actions:
            for col, (label, params) in zip(st.columns(len(actions)), actions):
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

    st.button("← Wróć do mapy", key="m3_back_from_editor", on_click=_leave_editor)


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


def render_profile_view(storage: Storage, user: User) -> None:
    """Publiczny profil innej osoby (opcjonalne)."""
    st.button("← Wróć do mapy", on_click=state.go_to, args=(View.MAP,), key="m3_back_from_profile")
    render_avatar(user, 96, caption=user.name)
    if user.bio:
        st.write(user.bio)
    if user.tags:
        st.markdown(" ".join(f"`{t}`" for t in user.tags))

    st.markdown("#### Wybiera się na")
    events = [storage.get_event(a.event_id) for a in storage.list_user_attendance(user.id)]
    for event in sorted((e for e in events if e), key=lambda e: e.start):
        st.markdown(f"- {event.meta.emoji} **{event.title}** — {format_when(event)}")
