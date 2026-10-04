"""
M5 — UI grup na wydarzenia („ekipy”). Logika (zasady, głosowania): m5_chat/groups.py.

    ┌ ← Mapa │ 🎵 Jam session jazzowy w piwnicy   [Grupa · 4|Wszyscy · 3] ┐  nazwa wydarzenia nad czatem;
    │        │ dziś · 20:00–23:00 · Alchemia · 4 osoby                    │  przełącznik: czat grupy albo
    │ (K)(B)(N)(o)                        [Zaproś ▾] [Opuść ▾]           │  czat wszystkich (to samo miejsce)
    │ ─────────── czat grupy (render_chat_room) ──────────────────────── │  głosowania = karty na czacie
    └────────────────────────────────────────────────────────────────────┘

Wejścia do czatu grupy: „Dodaj do ekipy” na karcie pasującej osoby (`open_event_chat`), lista „Idą /
Interesuje ich” z wyszukiwarką i „Czat wydarzenia” w panelu (`render_event_chat_entry`) i „Ekipy” (inbox.py).
Zaproszona osoba widzi nagłówek i skład grupy, ale treść czatu dopiero po dołączeniu.
Akcje zmieniające skład (dołącz, odrzuć, opuść, zaproś) są POZA fragmentem czatu -> pełny rerun odświeża
też panel wydarzenia. Głosy oddaje się w fragmencie; zmianę składu fragment wykrywa i robi pełny rerun.
"""

from __future__ import annotations

import html

import streamlit as st

from m3_profile.views import avatar_html
from m5_chat.groups import (
    GroupRole, InviteStatus, accept_invite, decline_invite, invite, invite_candidates, leave_group,
    member_group, received_invites, role_in, vote,
)
from m5_chat.service import escape_markdown, room_title
from shared import state
from shared.formatting import format_time, format_when
from shared.models import (
    ChatMessage, EventGroup, MessageKind, User, event_room_id, fold_text, group_room_id,
)
from shared.state import View
from shared.storage import Storage, get_storage

GROUP_CSS = """
.st-key-m5_crew_row {flex-wrap: nowrap !important;}
.st-key-m5_crew_row > [data-testid="stElementContainer"]:has(.m5-crew) {flex: 1 1 auto; min-width: 0;}
.m5-crew {display: flex; align-items: flex-start; gap: 10px; overflow-x: auto; padding: 4px 2px;
  scrollbar-width: thin;}
.m5-crew-item {display: flex; flex-direction: column; align-items: center; gap: 3px; flex: 0 0 54px;
  font-size: 0.72rem; line-height: 1.15; text-align: center;}
.m5-crew-item span {max-width: 54px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-weight: 600;}
.m5-crew-item em {font-style: normal; font-size: 0.62rem; opacity: 0.65;}
.m5-crew-wait > div:first-child {opacity: 0.45; outline: 2px dashed rgba(128, 128, 128, 0.7);
  outline-offset: 2px;}
.m5-crew-new > div:first-child {animation: m5-pop .7s cubic-bezier(.2, .9, .3, 1.4);}
@keyframes m5-pop {from {transform: scale(0.2); opacity: 0;} to {transform: scale(1); opacity: 1;}}
.m5-stack {display: flex; align-items: center;}
.m5-stack > div {box-shadow: 0 0 0 2px var(--krk-surface-solid, #fff);}
.m5-stack > div + div {margin-left: -8px;}
.m5-system {text-align: center; font-size: 0.78rem; opacity: 0.65; margin: 6px 0 12px;}
.m5-vote {display: flex; gap: 10px; align-items: center; padding: 10px 12px; border-radius: 14px;
  background: rgba(128, 128, 128, 0.10); border: 1px solid rgba(128, 128, 128, 0.22);}
.m5-vote b {display: block; line-height: 1.3;}
.m5-vote small {display: block; opacity: 0.7; margin-top: 2px;}
.m5-invite {display: flex; gap: 10px; align-items: center; line-height: 1.35;}
.m5-locked {text-align: center; padding: 48px 16px; opacity: 0.7; border-radius: 14px;
  border: 1px dashed rgba(128, 128, 128, 0.4);}
.m5-locked div {font-size: 2rem;}
[class*="st-key-m5_vote_"] {margin: 2px 0 14px;}
/* Lista osób: przewija się TYLKO ona. Okienko popovera dostaje od Streamlita max-height zależny od miejsca
   na ekranie i własny overflow:auto -> drugi suwak. Okienko bez przewijania, a lista kurczy się (flex). */
[data-testid="stPopoverBody"]:has([class*="st-key-m5_list_"]) {overflow: hidden; display: flex;
  flex-direction: column;}
[data-testid="stPopoverBody"]
  :is([data-testid="stVerticalBlock"], [data-testid="stLayoutWrapper"]):has([class*="st-key-m5_list_"]) {
  min-height: 0; flex: 0 1 auto; display: flex; flex-direction: column;
}
[data-testid="stLayoutWrapper"]:has(> [class*="st-key-m5_list_"]) {max-height: 340px;}
[class*="st-key-m5_list_"] {flex: 1 1 auto; min-height: 0; overflow-y: auto; scrollbar-width: thin;}
[class*="st-key-m5_row_"] {position: relative;}
[class*="st-key-m5_row_"] [data-testid="stMarkdownContainer"] {margin-bottom: 0;}  /* Streamlit: -1rem */
[class*="st-key-m5_row_"] [data-testid="stElementContainer"]:has(button) {
  position: absolute !important; inset: 0; z-index: 2; width: 100% !important; height: 100%;
}
[class*="st-key-m5_row_"] [data-testid="stElementContainer"]:has(button) > div,
[class*="st-key-m5_row_"] [data-testid="stButton"] {width: 100%; height: 100%;}
[class*="st-key-m5_row_"] button {width: 100%; height: 100%; min-height: 0; opacity: 0; cursor: pointer;}
.m5-person {display: flex; align-items: center; gap: 10px; padding: 6px 8px; border-radius: 10px;
  transition: background .15s ease;}
[class*="st-key-m5_row_"]:hover .m5-person {background: rgba(128, 128, 128, 0.12);}
.m5-person-text {flex: 1; min-width: 0; line-height: 1.25;}
.m5-person-text b, .m5-person-text small {display: block; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap;}
.m5-person-text small {opacity: 0.65; font-size: 0.74rem;}
.m5-person-add {font-size: 1.15rem; font-weight: 700; opacity: 0.45;}
[class*="st-key-m5_row_"]:hover .m5-person-add {opacity: 1; color: #E4572E;}
"""

PICKER_LIMIT = 30          # tyle osób rysujemy w liście naraz — resztę odsłania wyszukiwarka


def inject_group_css() -> None:
    st.html(f"<style>{GROUP_CSS}</style>")


def popover_heading(text: str) -> None:
    """Nagłówek sekcji w popoverach M5 (styl: M1 `.m5-pop-head`, jak etykiety w menu)."""
    st.markdown(f'<div class="m5-pop-head">{html.escape(text)}</div>', unsafe_allow_html=True)


def _people(n: int) -> str:
    """'1 osoba', '3 osoby', '5 osób', '12 osób'."""
    word = "osoba" if n == 1 else "osoby" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "osób"
    return f"{n} {word}"


def _toast_name(storage: Storage, user_id: str) -> str:
    user = storage.get_user(user_id)
    return escape_markdown(user.name if user else "Ta osoba")


# --------------------------------------------------------------------------- #
# Callbacki (przed przebiegiem skryptu -> cała strona widzi nowy stan w jednym rerunie)
# --------------------------------------------------------------------------- #

def open_group(group_id: str, event_id: str | None = None) -> None:
    """Otwiera czat grupy; z `event_id` prawy panel pokazuje jej wydarzenie (i „Pasujące osoby”)."""
    if event_id is not None:
        state.select_event(event_id)
    state.go_to(View.CHAT, room_id=group_room_id(group_id))


def _invite_and_open(storage: Storage, event_id: str, me_id: str, other_id: str) -> None:
    result = invite(storage, event_id, me_id, other_id)
    if result is None:
        return
    name = _toast_name(storage, other_id)
    if result.status is InviteStatus.SENT:
        st.toast(f"Zaproszenie wysłane: {name} — napisz coś na powitanie", icon=":material/mail:")
    elif result.status is InviteStatus.VOTING:
        st.toast(f"Zaproszenie dla: {name} czeka na głosy grupy", icon=":material/how_to_vote:")
    elif result.status is InviteStatus.ALREADY_INVITED:
        st.toast(f"{name} ma już zaproszenie do Twojej grupy", icon=":material/schedule:")
    open_group(result.group.id, event_id)


def open_event_chat(me_id: str, other_id: str, event_id: str, storage: Storage | None = None) -> None:
    """Callback „Dodaj do ekipy” na karcie pasującej osoby (M3): czat w kontekście wydarzenia, nie DM.

    Bez grupy, gdy ta osoba zaprasza mnie do swojej -> pokazuje jej zaproszenie. W przeciwnym razie
    zaprasza ją do mojej grupy (zakłada ją; w większej grupie startuje głosowanie) i otwiera czat grupy.
    """
    storage = storage or get_storage()
    if me_id == other_id:
        return
    if member_group(storage, event_id, me_id) is None:
        for group, _ in received_invites(storage, me_id, event_id=event_id):
            if other_id in group.members:
                open_group(group.id, event_id)
                return
    _invite_and_open(storage, event_id, me_id, other_id)


def team_action_label(me_id: str, other_id: str, event_id: str, storage: Storage | None = None) -> str:
    """Etykieta przycisku na karcie pasującej osoby (M3) — co zrobi `open_event_chat` dla tej osoby."""
    storage = storage or get_storage()
    group = member_group(storage, event_id, me_id)
    if group is None:
        if any(other_id in g.members for g, _ in received_invites(storage, me_id, event_id=event_id)):
            return "✉️ Zaproszenie"                     # ta osoba zaprasza mnie do swojej ekipy
        return "➕ Dodaj do ekipy"
    if other_id in group.members:
        return "💬 Czat ekipy"
    if group.invite_for(other_id) is not None:
        return "⏳ Zaproszono"
    return "➕ Dodaj do ekipy"


def _on_invite(
    storage: Storage, event_id: str, me_id: str, other_id: str, popover_key: str, query_key: str,
) -> None:
    st.session_state[popover_key] = False
    st.session_state[query_key] = ""                    # następne otwarcie listy bez starego filtra
    _invite_and_open(storage, event_id, me_id, other_id)


def _on_accept(storage: Storage, group_id: str, user_id: str) -> None:
    if accept_invite(storage, group_id, user_id) is not None:
        st.toast("Witaj w grupie! Przywitaj się na czacie 👋")


def _on_decline(storage: Storage, group_id: str, user_id: str) -> None:
    decline_invite(storage, group_id, user_id)
    state.go_to(View.MAP)
    st.toast("Zaproszenie odrzucone")


def _on_leave(storage: Storage, group_id: str, user_id: str) -> None:
    if leave_group(storage, group_id, user_id):
        st.toast("Opuszczono grupę", icon=":material/logout:")
    state.go_to(View.MAP)


def _on_vote(storage: Storage, group_id: str, invite_id: str, voter_id: str, approve: bool) -> None:
    vote(storage, group_id, invite_id, voter_id, approve)


# --------------------------------------------------------------------------- #
# Lista „Idą + Interesuje mnie” (ten sam dropdown w panelu wydarzenia i nad czatem grupy)
# --------------------------------------------------------------------------- #

def matches_person(person: User, query: str) -> bool:
    """Wyszukiwarka osób: imię albo zainteresowanie, bez wielkości liter i polskich znaków."""
    needle = fold_text(query.strip())
    return not needle or needle in fold_text(f"{person.name} {' '.join(person.tags)}")


def _person_row_html(person: User) -> str:
    tags = " · ".join(person.tags[:3])
    small = f"<small>{html.escape(tags)}</small>" if tags else ""
    return (
        f'<div class="m5-person">{avatar_html(person, 32)}'
        f'<div class="m5-person-text"><b>{html.escape(person.name)}</b>{small}</div>'
        '<span class="m5-person-add">+</span></div>'
    )


def render_invite_popover(
    storage: Storage, event_id: str, user: User, group: EventGroup | None, *, label: str, key: str,
    width: str | int = "content",
) -> None:
    """Lista „Idą + Interesuje mnie” jednym ciągiem (najpierw idący) z wyszukiwarką; wiersz = awatar, imię,
    zainteresowania (cały klikalny)."""
    query_key = f"m5_q_{key}"
    with (
        st.popover(label, icon=":material/person_add:", key=key, on_change="rerun", width=width),
        st.container(key=f"m5_pop_{key}", gap=None),
    ):
        everyone = invite_candidates(storage, event_id, user.id, group)
        if group is not None and len(group.members) > 1:
            st.caption("Każdą nową osobę zatwierdza cała grupa — głosowanie pojawi się na czacie.")
        elif everyone:
            st.caption("Zaproszona osoba zobaczy czat Waszej grupy i zdecyduje, czy dołącza.")
        if not everyone:
            st.caption("Nikogo więcej tu nie ma. Gdy ktoś kliknie „Idę!” albo „Interesuje mnie”, "
                       "pojawi się na tej liście.")
            return
        query = st.text_input(
            "Szukaj osoby", key=query_key, placeholder="Szukaj: imię albo zainteresowanie",
            icon=":material/search:", label_visibility="collapsed",
        )
        people = [person for person, _ in everyone if matches_person(person, query or "")]
        if not people:
            st.caption(f"Nikt nie pasuje do „{escape_markdown(query.strip())}”.")
        with st.container(key=f"m5_list_{key}", gap=None):
            for person in people[:PICKER_LIMIT]:
                # Prefiksy inne niż klucz popovera: style M1 dla `m5_grp_new_*` omijają listę.
                with st.container(key=f"m5_row_{key}_{person.id}", gap=None):
                    st.markdown(_person_row_html(person), unsafe_allow_html=True)
                    st.button(
                        escape_markdown(person.name), key=f"m5_pick_{key}_{person.id}",
                        help=f"Dodaj do ekipy: {escape_markdown(person.name)}", on_click=_on_invite,
                        args=(storage, event_id, user.id, person.id, key, query_key),
                    )
        if len(people) > PICKER_LIMIT:
            st.caption(f"…i jeszcze {_people(len(people) - PICKER_LIMIT)} — zawęź wyszukiwanie.")


# --------------------------------------------------------------------------- #
# Panel wydarzenia (M1): zaproszenia do grup, czat grupy (albo „Zaproś”) i czat wydarzenia
# --------------------------------------------------------------------------- #

def _stack_html(storage: Storage, user_ids: list[str], size: int = 28) -> str:
    users = storage.get_users(user_ids)
    avatars = "".join(avatar_html(users[u], size) for u in user_ids if u in users)
    return f'<div class="m5-stack">{avatars}</div>'


def open_event_room(event_id: str) -> None:
    """Publiczny czat wydarzenia (wszyscy zapisani i zainteresowani) — w tym samym arkuszu co czat grupy."""
    state.go_to(View.CHAT, room_id=event_room_id(event_id))


def render_event_chat_entry(storage: Storage, event_id: str, user: User) -> None:
    """Panel wydarzenia: zaproszenia do grup, a pod nimi obok siebie czat grupy (albo „Zaproś”)
    i czat wszystkich uczestników wydarzenia."""
    inject_group_css()
    group = member_group(storage, event_id, user.id)
    for other, invitation in received_invites(storage, user.id, event_id=event_id):
        inviter = storage.get_user(invitation.invited_by)
        who = html.escape(inviter.name) if inviter else "Ktoś"
        with st.container(key=f"m5_grp_invite_{other.id}", border=True):
            st.html(
                f'<div class="m5-invite">{_stack_html(storage, other.members)}<div><b>{who}</b> '
                f"zaprasza Cię do swojej ekipy ({_people(len(other.members))}).</div></div>"
            )
            st.button("Zobacz zaproszenie", key=f"m5_grp_view_{other.id}", icon=":material/mail:",
                      on_click=open_group, args=(other.id, event_id), width="stretch")
    with st.container(key="m5_chat_entry", horizontal=True, gap="small"):
        if group is not None:
            st.button(
                f"Czat grupy · {len(group.members)}", key=f"m5_grp_open_{event_id}", icon=":material/groups:",
                on_click=open_group, args=(group.id, event_id), width="stretch",
                help=f"Twoja ekipa na to wydarzenie: {_people(len(group.members))}",
            )
        else:
            render_invite_popover(storage, event_id, user, None, label="Zbierz ekipę",
                                  key=f"m5_grp_new_{event_id}", width="stretch")
        messages = storage.count_messages(event_room_id(event_id))
        st.button(
            "Czat wydarzenia", key=f"m5_evt_open_{event_id}", icon=":material/forum:",
            on_click=open_event_room, args=(event_id,), width="stretch",
            help=f"Czat wszystkich, którzy idą lub są zainteresowani · wiadomości: {messages}",
        )


# --------------------------------------------------------------------------- #
# Przełącznik „Grupa / Wszyscy” w nagłówku czatu wydarzenia i czatu grupy
# --------------------------------------------------------------------------- #

def _switch_group(storage: Storage, event_id: str, user_id: str) -> EventGroup | None:
    """Grupa do przełącznika: moja, a bez niej — ta, która mnie zaprasza (podgląd zaproszenia)."""
    if group := member_group(storage, event_id, user_id):
        return group
    invites = received_invites(storage, user_id, event_id=event_id)
    return invites[0][0] if invites else None


def _on_switch(key: str) -> None:
    if room_id := st.session_state[key]:            # ponowny klik w zaznaczoną opcję = None -> zostajemy
        state.go_to(View.CHAT, room_id=room_id)


def render_chat_switch(storage: Storage, user: User, event_id: str, room_id: str) -> None:
    """Czat grupy i czat wszystkich zajmują to samo miejsce — przełącznik zamienia pokój w arkuszu.
    Bez grupy: „Zaproś” (ta sama lista co w panelu) zamiast przełącznika."""
    group = _switch_group(storage, event_id, user.id)
    if group is None:
        render_invite_popover(storage, event_id, user, None, label="Zbierz ekipę",
                              key=f"m5_chat_invite_{event_id}")
        return
    options = {
        group_room_id(group.id): f"Grupa · {len(group.members)}",
        event_room_id(event_id): f"Wszyscy · {storage.count_messages(event_room_id(event_id))}",
    }
    key = f"m5_switch_{event_id}"
    st.session_state[key] = room_id                  # stan zawsze z otwartego pokoju (np. wejście z panelu)
    st.segmented_control(
        "Czat", list(options), format_func=options.get, key=key, on_change=_on_switch, args=(key,),
        label_visibility="collapsed",
    )


# --------------------------------------------------------------------------- #
# Nagłówek czatu grupy (poza fragmentem)
# --------------------------------------------------------------------------- #

def group_signature(group: EventGroup | None) -> tuple:
    """Skład i stan zaproszeń — zmiana = fragment czatu robi pełny rerun (nagłówek, panel, skrzynka)."""
    if group is None:
        return ()
    return tuple(group.members), tuple((i.id, i.is_sent, tuple(i.approvals)) for i in group.invites)


def crew_html(storage: Storage, group: EventGroup, *, fresh: frozenset[str] = frozenset()) -> str:
    """Rząd awatarów: członkowie w kolejności dołączenia (nowi z animacją), potem zaproszeni (wyszarzeni)."""
    users = storage.get_users([*group.members, *(i.user_id for i in group.invites)])
    items = []
    for user_id in group.members:
        if user := users.get(user_id):
            cls = "m5-crew-item m5-crew-new" if user_id in fresh else "m5-crew-item"
            items.append(
                f'<div class="{cls}">{avatar_html(user, 40)}<span>{html.escape(user.name)}</span></div>'
            )
    for invitation in group.invites:
        if user := users.get(invitation.user_id):
            note = "zaproszenie" if invitation.is_sent else "głosowanie"
            items.append(
                f'<div class="m5-crew-item m5-crew-wait">{avatar_html(user, 40)}'
                f"<span>{html.escape(user.name)}</span><em>{note}</em></div>"
            )
    return f'<div class="m5-crew">{"".join(items)}</div>'


def _fresh_members(group: EventGroup) -> frozenset[str]:
    """Kto doszedł od poprzedniego rysowania (animacja wejścia awatara); pierwsze wejście bez animacji."""
    seen_key = f"m5_crew_seen_{group.id}"
    seen = st.session_state.get(seen_key)
    st.session_state[seen_key] = set(group.members)
    return frozenset(set(group.members) - seen) if seen is not None else frozenset()


def render_group_head(storage: Storage, user: User, group_id: str) -> GroupRole:
    """„← Mapa”, nazwa wydarzenia, rząd awatarów i akcje (zaproś / opuść) albo zaproszenie do grupy."""
    inject_group_css()
    group = storage.get_group(group_id)
    role = role_in(group, user.id)
    col_back, col_title, col_switch = st.columns([1, 4, 2.4], vertical_alignment="center")
    with col_back:
        st.button("← Mapa", on_click=state.go_to, args=(View.MAP,), key="m5_back")
    if role is GroupRole.NONE:
        col_title.warning("🔒 Nie należysz do tej grupy — mogła zostać rozwiązana albo zaproszenie wygasło.")
        return role

    event = storage.get_event(group.event_id)
    with col_title:
        st.markdown(f"### {escape_markdown(room_title(storage, group_room_id(group.id)))}")
        where = f"{format_when(event)} · {event.venue} · " if event is not None else ""
        st.caption(escape_markdown(f"{where}{_people(len(group.members))} w grupie"))
    with col_switch:
        render_chat_switch(storage, user, group.event_id, group_room_id(group.id))

    with st.container(key="m5_crew_row", horizontal=True, vertical_alignment="center"):
        st.html(crew_html(storage, group, fresh=_fresh_members(group)))
        if role is GroupRole.MEMBER:
            render_invite_popover(storage, group.event_id, user, group, label="Zaproś",
                                  key=f"m5_grp_add_{group.id}")
            with st.popover("Opuść", icon=":material/logout:", key=f"m5_grp_leave_{group.id}"):
                st.caption("Nie zobaczysz już czatu tej grupy. Wrócić możesz tylko z nowym zaproszeniem.")
                st.button("Opuść grupę", key=f"m5_grp_leave_btn_{group.id}", type="primary",
                          on_click=_on_leave, args=(storage, group.id, user.id))

    if role is GroupRole.INVITED:
        _render_invite_banner(storage, user, group)
        count = storage.count_messages(group_room_id(group.id))
        st.html(
            '<div class="m5-locked"><div>🔒</div>Wiadomości grupy zobaczysz po dołączeniu'
            f" · {count} {'wiadomość' if count == 1 else 'wiadomości'}</div>"
        )
    return role


def _render_invite_banner(storage: Storage, user: User, group: EventGroup) -> None:
    invitation = group.invite_for(user.id)
    inviter = storage.get_user(invitation.invited_by)
    who = escape_markdown(inviter.name) if inviter else "Ktoś"
    with st.container(key="m5_grp_banner", border=True):
        st.markdown(f"**{who}** zaprasza Cię do swojej ekipy na to wydarzenie. Dołączysz?")
        if member_group(storage, group.event_id, user.id) is not None:
            st.caption("Masz już grupę na to wydarzenie — dołączając, opuścisz ją "
                       "(jedno wydarzenie = jedna grupa).")
        else:
            st.caption("Treść czatu zobaczysz po dołączeniu — do tego czasu masz „Wszyscy” obok.")
        with st.container(horizontal=True):
            st.button("Dołącz", key=f"m5_grp_accept_{group.id}", type="primary",
                      icon=":material/group_add:", on_click=_on_accept, args=(storage, group.id, user.id))
            st.button("Odrzuć", key=f"m5_grp_decline_{group.id}", icon=":material/close:",
                      on_click=_on_decline, args=(storage, group.id, user.id))


# --------------------------------------------------------------------------- #
# Komunikaty i karty głosowań w strumieniu czatu (w fragmencie)
# --------------------------------------------------------------------------- #

def render_group_notice(
    storage: Storage, message: ChatMessage, group: EventGroup | None, viewer_id: str,
) -> None:
    if message.kind is MessageKind.VOTE:
        _render_vote_card(storage, message, group, viewer_id)
        return
    when = html.escape(format_time(message.created_at))
    st.html(f'<div class="m5-system">{html.escape(message.text)} · {when}</div>')


def _render_vote_card(
    storage: Storage, message: ChatMessage, group: EventGroup | None, viewer_id: str,
) -> None:
    """Karta zaproszenia: wynik głosowania na żywo i przyciski dla członków, którzy jeszcze nie głosowali."""
    invitation = next((i for i in group.invites if i.id == message.ref), None) if group else None
    icon = "🗳️"
    if invitation is None:
        status = "Zakończone"
    elif invitation.is_sent:
        icon, status = "✉️", "Zaproszenie wysłane — czekamy na odpowiedź"
    else:
        missing = [m for m in group.members if m not in invitation.approvals]
        names = ", ".join(u.name for u in storage.get_users(missing).values())
        status = f"Za: {len(group.members) - len(missing)}/{len(group.members)} · czekamy na: {names}"
    with st.container(key=f"m5_vote_{message.id}", gap="small"):
        st.html(
            f'<div class="m5-vote"><div style="font-size:1.4rem">{icon}</div><div>'
            f"<b>{html.escape(message.text)}</b><small>{html.escape(status)}</small></div></div>"
        )
        if invitation is None or invitation.is_sent or group is None or viewer_id not in group.members:
            return
        if viewer_id in invitation.approvals:
            st.caption("Twój głos: za ✅")
            return
        with st.container(horizontal=True):
            args = (storage, group.id, invitation.id, viewer_id)
            st.button("Za", key=f"m5_vote_yes_{message.id}", icon=":material/thumb_up:", type="primary",
                      on_click=_on_vote, args=(*args, True))
            st.button("Przeciw", key=f"m5_vote_no_{message.id}", icon=":material/thumb_down:",
                      on_click=_on_vote, args=(*args, False))
