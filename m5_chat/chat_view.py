"""
M5 — UI czatu i interakcji społecznościowych.

Czat z pollingiem przez @st.fragment(run_every=...) — odświeża się TYLKO okienko czatu,
a nie cała aplikacja (mapa się nie przeładowuje).
Układ: kolejne wiadomości jednej osoby to grupa. Cudze grupy po lewej, z klikalnym awatarem
i imieniem (-> profil autora); własne po prawej, w kolorze akcentu. Tekst w dymkach
przez html.escape -> zawsze dosłownie.
"""

from __future__ import annotations

import html
import time
import zlib
from collections.abc import Iterable

import streamlit as st

from m5_chat.service import (
    BUFFER_LIMIT, MAX_MESSAGE_LEN, Conversation, attendance_counts, can_access_room, css_string, escape_markdown,
    group_messages, list_conversations, refresh_messages, room_title, safe_avatar_src, seconds_until_allowed,
    send_message, set_attendance,
)
from shared import state
from shared.config import CHAT_POLL_SECONDS, FEATURES
from shared.formatting import format_time
from shared.models import AttendanceStatus, ChatMessage, Event, User, dm_room_id
from shared.state import View
from shared.storage import Storage

AVATAR_SIZE = 36
# Rysowanie wiadomości to większość kosztu ticka -> pokazujemy ostatnie N, starsze na żądanie.
SHOW_STEP = 50
# Te same kolory co awatary z inicjałami w m3_profile.views (ta sama osoba = ten sam kolor wszędzie).
_AVATAR_COLORS = ["#E4572E", "#17BEBB", "#FFC914", "#2E282A", "#76B041", "#7E5BEF", "#F46197"]

# Nagłówek cudzej grupy = JEDEN st.button (tertiary) z imieniem; awatar rysuje CSS w `::before`
# (kolor/zdjęcie/inicjały per osoba przez klasę `st-key-<key>`). Mniej elementów = szybszy tick.
# Kolory dymków półprzezroczyste -> czytelne w jasnym i ciemnym motywie.
_BASE_CSS = f"""
.st-key-m5_css {{display: none;}}
[class*="st-key-m5_av"] button {{gap: 8px; min-height: {AVATAR_SIZE}px;}}
[class*="st-key-m5_av"] button::before {{
  content: "?"; flex: 0 0 {AVATAR_SIZE}px; width: {AVATAR_SIZE}px; height: {AVATAR_SIZE}px;
  display: flex; align-items: center; justify-content: center; border-radius: 50%;
  background: #9e9e9e center / cover no-repeat; color: #fff; font-weight: 600; font-size: 14px;
}}
[class*="st-key-m5_av"] button:hover::before {{filter: brightness(0.9);}}
[class*="st-key-m5_av"] button:disabled {{opacity: 1; cursor: default;}}
[class*="st-key-m5_older_"] {{margin-bottom: 8px;}}
.m5-bubbles {{display: flex; flex-direction: column; align-items: flex-start; gap: 3px; margin: 2px 0 14px;}}
.m5-bubbles.m5-theirs {{margin-left: {AVATAR_SIZE + 8}px;}}
.m5-bubbles.m5-mine {{align-items: flex-end;}}
.m5-bubble {{
  max-width: 80%; padding: 6px 12px; border-radius: 16px; line-height: 1.45;
  white-space: pre-wrap; overflow-wrap: anywhere; background: rgba(128, 128, 128, 0.14);
}}
.m5-mine .m5-bubble {{background: rgba(228, 87, 46, 0.18);}}
.m5-time {{float: right; margin: 5px 0 0 10px; font-size: 0.72em; opacity: 0.6; white-space: nowrap;}}
.m5-empty {{text-align: center; padding: 64px 16px; opacity: 0.7;}}
.m5-empty-icon {{font-size: 2.4rem;}}
"""

_EMPTY_HTML = (
    '<div class="m5-empty"><div class="m5-empty-icon">💬</div>'
    "Jeszcze cisza…<br>Napisz pierwszą wiadomość 👋</div>"
)


def _avatar_key_prefix(user_id: str) -> str:
    """Prefiks klucza przycisku-nagłówka: stały dla osoby i bezpieczny w CSS (hash zamiast surowego ID)."""
    return f"m5_av{zlib.crc32(user_id.encode()):08x}_"


def _author_css(author: User) -> str:
    """Awatar jednej osoby: inicjały, kolor, zdjęcie (raz na osobę, a nie przy każdej wiadomości)."""
    selector = f'[class*="st-key-{_avatar_key_prefix(author.id)}"] button::before'
    color = _AVATAR_COLORS[zlib.crc32(author.id.encode()) % len(_AVATAR_COLORS)]
    rules = f'content: "{css_string(author.initials)}"; background-color: {color};'
    if src := safe_avatar_src(author.avatar_url):
        rules += f'background-image: url("{src}"); color: transparent;'
    return f"{selector} {{{rules}}}"


def _inject_css(authors: Iterable[User]) -> None:
    with st.container(key="m5_css"):
        css = _BASE_CSS + "\n".join(_author_css(a) for a in authors)
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _bubbles_html(messages: list[ChatMessage], *, mine: bool) -> str:
    """Dymki jednej grupy (jeden element st.html). Tekst przez html.escape -> bez HTML i markdownu."""
    bubbles = "".join(
        f'<div class="m5-bubble" title="{m.created_at:%d.%m.%Y %H:%M}">{html.escape(m.text)}'
        f'<span class="m5-time">{html.escape(format_time(m.created_at))}</span></div>'
        for m in messages
    )
    return f'<div class="m5-bubbles {"m5-mine" if mine else "m5-theirs"}">{bubbles}</div>'


def _render_group(group: list[ChatMessage], author: User | None, *, can_open_profile: bool) -> bool:
    """Cudza grupa: nagłówek [awatar] imię (jeden przycisk -> profil), pod nim dymki.

    Zwraca True, gdy kliknięto nagłówek (awatar albo imię autora).
    """
    first = group[0]
    name = author.name if author else "Nieznana osoba"
    clickable = can_open_profile and author is not None
    clicked = st.button(
        f"**{escape_markdown(name)}**", key=f"{_avatar_key_prefix(first.user_id)}{first.id}", type="tertiary",
        help=f"Zobacz profil: {escape_markdown(name)}" if clickable else None, disabled=not clickable,
    )
    st.html(_bubbles_html(group, mine=False))
    return clicked


def render_chat_room(storage: Storage, user: User, room_id: str, *, height: int = 520) -> None:
    """Pełny widok czatu w środkowym obszarze (zamiast mapy): czat wydarzenia albo prywatna rozmowa."""
    col_back, col_title = st.columns([1, 5], vertical_alignment="center")
    with col_back:
        st.button("← Mapa", on_click=state.go_to, args=(View.MAP,), key="m5_back")
    if not can_access_room(room_id, user.id):
        # Np. po „Zaloguj jako” z otwartym DM poprzedniej osoby — nie pokazujemy cudzej rozmowy.
        col_title.warning("🔒 To prywatna rozmowa innych osób.")
        return
    with col_title:
        # Tytuł eventu (scraper, formularz M2) i imiona w DM to dane z zewnątrz -> bez markdownu.
        st.markdown(f"### {escape_markdown(room_title(storage, room_id, viewer_id=user.id))}")

    buf_key, show_key = f"m5_buf_{room_id}", f"m5_show_{room_id}"
    # Ten kod NIE wykonuje się w tickach fragmentu, tylko przy pełnym rerunie (wejście do pokoju,
    # „Reset demo”, zmiana użytkownika) -> wtedy bufor ładujemy od nowa; ticki dociągają tylko nowości.
    st.session_state[buf_key] = storage.list_messages(room_id, limit=BUFFER_LIMIT)

    @st.fragment(run_every=CHAT_POLL_SECONDS)
    def _live_chat() -> None:
        started = time.perf_counter()
        # Okno wiadomości rezerwujemy NAD polem wpisywania, ale wypełniamy je dopiero po obsłudze wysyłki:
        # nowa wiadomość jest widoczna w tym samym przebiegu, bez dodatkowego st.rerun().
        # autoscroll trzyma dół tylko, gdy użytkownik sam nie przewinął w górę. Odstępy grup daje CSS (gap=None).
        chat_box = st.container(height=height, autoscroll=True, gap=None)
        text = st.chat_input("Napisz wiadomość…", key=f"m5_input_{room_id}", max_chars=MAX_MESSAGE_LEN)
        if text:
            _send_with_limit(storage, room_id, user.id, text)

        buffer = refresh_messages(storage, room_id, st.session_state.get(buf_key, []))
        st.session_state[buf_key] = buffer
        visible = buffer[-st.session_state.get(show_key, SHOW_STEP):]
        authors = storage.get_users({m.user_id for m in visible})
        can_open_profile = FEATURES["profile_view"]
        _inject_css(a for a in authors.values() if a.id != user.id)   # własny awatar nie jest wyświetlany

        opened_user_id: str | None = None
        with chat_box:
            if len(visible) < len(buffer):
                st.button(
                    "⬆ Pokaż starsze", key=f"m5_older_{room_id}", type="tertiary",
                    on_click=_show_more, args=(show_key, len(visible)),
                )
            if not visible:
                st.html(_EMPTY_HTML)
            for group in group_messages(visible):
                author_id = group[0].user_id
                if author_id == user.id:
                    st.html(_bubbles_html(group, mine=True))
                elif _render_group(group, authors.get(author_id), can_open_profile=can_open_profile):
                    opened_user_id = author_id
        if opened_user_id:
            state.go_to(View.PROFILE_VIEW, user_id=opened_user_id)
            st.rerun()  # pełny rerun: wybór widoku (app.py) jest poza fragmentem

        st.session_state["m5_tick_ms"] = tick_ms = (time.perf_counter() - started) * 1000
        if st.query_params.get("m5_debug"):
            st.caption(f"⏱ tick {tick_ms:.1f} ms · bufor {len(buffer)} · widocznych {len(visible)}")

    _live_chat()


def _show_more(show_key: str, shown: int) -> None:
    st.session_state[show_key] = shown + SHOW_STEP


def _send_with_limit(storage: Storage, room_id: str, user_id: str, text: str) -> bool:
    """Wysyła wiadomość, o ile sesja nie przekroczyła limitu (1 na sekundę). True = zapisano.

    Zablokowanej treści nie da się wstawić z powrotem do st.chat_input, więc pokazujemy ją w komunikacie.
    """
    now = time.monotonic()
    if seconds_until_allowed(st.session_state.get("m5_last_sent_at"), now) > 0:
        flat = " ".join(text.split())
        excerpt = flat if len(flat) <= 60 else flat[:60] + "…"
        st.toast(
            f"Zwolnij 🙂 Maks. 1 wiadomość na sekundę — nie wysłano: „{escape_markdown(excerpt)}”", icon="⏳",
        )
        return False
    if send_message(storage, room_id, user_id, text) is None:
        return False
    st.session_state["m5_last_sent_at"] = now
    return True


_STATUS_LABELS = {AttendanceStatus.GOING: "🙋 Idę!", AttendanceStatus.INTERESTED: "⭐ Interesuje mnie"}


def render_attendance_controls(storage: Storage, event: Event, user: User) -> None:
    """Zapis na wydarzenie: status (Idę! / Interesuje mnie; ponowny klik = rezygnacja) + zgoda na dopasowania.

    Wszystko przez callbacki: zapis trafia do bazy PRZED przebiegiem skryptu, więc licznik zapisanych
    w panelu (M1) i dopasowania (M4) pokazują nowy stan w tym samym, jedynym rerunie.
    """
    attendance = storage.get_attendance(user.id, event.id)
    # Klucze per osoba i wydarzenie (przełącznik „Zaloguj jako” nie przenosi stanu na inną osobę),
    # a stan widgetów zawsze z bazy (inna karta, „Reset demo”).
    status_key, open_key = f"m5_status_{user.id}_{event.id}", f"m5_open_{user.id}_{event.id}"
    st.session_state[status_key] = attendance.status if attendance else None
    st.segmented_control(
        "Twój udział", list(AttendanceStatus), format_func=_STATUS_LABELS.get, key=status_key,
        on_change=_on_status_change, args=(storage, user.id, event.id, status_key),
        label_visibility="collapsed", width="stretch",
    )
    counts = attendance_counts(storage, event.id)
    st.caption(
        f"🙋 Idzie: **{counts[AttendanceStatus.GOING]}** · "
        f"⭐ Zainteresowani: **{counts[AttendanceStatus.INTERESTED]}**"
    )
    if attendance is None:
        return

    st.session_state[open_key] = attendance.open_to_meet
    st.toggle(
        "Pokaż mnie innym w dopasowaniach", key=open_key,
        on_change=_on_open_to_meet_change, args=(storage, user.id, event.id, attendance.status, open_key),
    )
    st.button(
        "Rezygnuję", key=f"m5_leave_{user.id}_{event.id}", type="tertiary",
        on_click=set_attendance, args=(storage, user.id, event.id, None),
    )


def _on_status_change(storage: Storage, user_id: str, event_id: str, status_key: str) -> None:
    set_attendance(storage, user_id, event_id, st.session_state[status_key])


def _on_open_to_meet_change(
    storage: Storage, user_id: str, event_id: str, status: AttendanceStatus, open_key: str,
) -> None:
    set_attendance(storage, user_id, event_id, status, open_to_meet=st.session_state[open_key])


# --------------------------------------------------------------------------- #
# Prywatne rozmowy (DM) — włączane flagą FEATURES["dm_chat"] po stronie wywołujących (M1, M3)
# --------------------------------------------------------------------------- #

def open_dm(me_id: str, other_id: str) -> None:
    """Callback przycisku „Napisz” (karta osoby M3, lista rozmów): otwiera prywatny czat z `other_id`.

    Użycie: st.button("✉️ Napisz", key=..., on_click=open_dm, args=(me.id, other.id)).
    Wołaj poza @st.fragment — zmiana widoku wymaga pełnego reruna.
    """
    if me_id != other_id:
        state.go_to(View.CHAT, room_id=dm_room_id(me_id, other_id))


def render_dm_list(storage: Storage, user: User, *, limit: int = 8) -> None:
    """„Moje rozmowy”: prywatne czaty od najświeższej; klik otwiera rozmowę (open_dm)."""
    conversations = list_conversations(storage, user.id)
    if not conversations:
        st.caption("Brak prywatnych rozmów — napisz do kogoś z listy „Pasujące osoby” 🙂")
        return
    current = state.chat_room_id() if state.current_view() is View.CHAT else None
    for conv in conversations[:limit]:
        st.button(
            _conversation_label(conv, user.id), key=f"m5_dm_{conv.room_id}",
            type="secondary" if conv.room_id == current else "tertiary",
            on_click=open_dm, args=(user.id, conv.other.id),
        )


def _conversation_label(conv: Conversation, me_id: str) -> str:
    """'**Kuba** · 18:02 — Ty: hej, będziesz…' (dane użytkowników bez markdownu)."""
    first_line = " ".join(conv.last.text.splitlines()[0].split())
    preview = first_line if len(first_line) <= 32 else first_line[:32] + "…"
    if conv.last.user_id == me_id:
        preview = f"Ty: {preview}"
    return (
        f"**{escape_markdown(conv.other.name)}** · {escape_markdown(format_time(conv.last.created_at))}"
        f" — {escape_markdown(preview)}"
    )

