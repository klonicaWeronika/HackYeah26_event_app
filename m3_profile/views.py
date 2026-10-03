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
from shared.config import FEATURES
from shared.formatting import format_when
from shared.models import INTEREST_TAGS, MatchResult, User
from shared.storage import Storage
from shared.state import View

_AVATAR_COLORS = ["#E4572E", "#17BEBB", "#FFC914", "#2E282A", "#76B041", "#7E5BEF", "#F46197"]


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
    """'Zaloguj jako…' — w MVP nie ma haseł; wybór osoby z bazy."""
    users = storage.list_users()
    ids = [u.id for u in users]
    names = {u.id: u.name for u in users}
    current = state.current_user_id()

    def _on_change() -> None:
        state.set_current_user(st.session_state[key])
        state.select_event(None)

    st.selectbox(
        "Zaloguj jako",
        ids,
        index=ids.index(current) if current in ids else 0,
        format_func=names.get,
        key=key,
        on_change=_on_change,
    )


def render_user_card(user: User, match: MatchResult | None = None, *, key: str) -> None:
    """Kompaktowa karta osoby (lista dopasowań w prawym panelu, lista uczestników)."""
    with st.container(border=True):
        col_avatar, col_body = st.columns([1, 4], vertical_alignment="center")
        with col_avatar:
            st.markdown(avatar_html(user, 44), unsafe_allow_html=True)
        with col_body:
            title = f"**{user.name}**"
            if match is not None:
                title += f" · {match.score:.0%} dopasowania"
            st.markdown(title)
            if match and match.reason:
                st.caption(match.reason)
            elif user.bio:
                st.caption(user.bio[:90])
        if FEATURES["profile_view"]:
            st.button(
                "Zobacz profil", key=key, type="tertiary",
                on_click=state.go_to, args=(View.PROFILE_VIEW,), kwargs={"user_id": user.id},
            )


# --------------------------------------------------------------------------- #
# Zdjęcie profilowe (M3-02): uploader POZA st.form + szkic w session_state
# --------------------------------------------------------------------------- #

_AVATAR_DRAFT = "m3_avatar_draft"     # {"user_id": str, "avatar_url": str | None} — niezapisana zmiana zdjęcia
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
        ss.get(_pe_key("name", key_id), ""), ss.get(_pe_key("bio", key_id), ""), ss.get(_pe_key("tags", key_id), []),
    )
    if errors:
        ss[_PE_ERRORS] = {"user_id": key_id, "errors": errors}
    else:
        ss.pop(_PE_ERRORS, None)
    return clean, errors


def _on_save_profile(storage: Storage, user_id: str) -> None:
    """„Zapisz” (on_click): walidacja -> zapis -> toast + mapa w jednym rerunie. Błąd = zostajemy w edytorze."""
    clean, errors = _validated_fields(user_id)
    if errors:
        return
    user = storage.get_user(user_id)
    if user is None:                                       # np. „Reset danych demo” w innej karcie
        st.session_state[_PE_ERRORS] = {"user_id": user_id, "errors": {"name": "Ten profil już nie istnieje."}}
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
    """Edycja własnego profilu: zdjęcie (upload -> data URI), imię, bio, zainteresowania."""
    st.subheader("✏️ Twój profil")
    _render_avatar_picker(user)

    with st.form(f"m3_pe_form_{user.id}"):
        _render_profile_fields(storage, key_id=user.id, name=user.name, bio=user.bio, tags=user.tags)
        st.form_submit_button("Zapisz", type="primary", on_click=_on_save_profile, args=(storage, user.id))

    st.button("← Wróć do mapy", key="m3_back_from_editor", on_click=_leave_editor)


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
