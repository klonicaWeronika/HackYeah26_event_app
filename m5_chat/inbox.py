"""
M5 — skrzynka „Ekipy” w górnym pasku (zaproszenia, głosowania, moje grupy, prywatne rozmowy)
i powiadomienia: toast o nowym zaproszeniu / głosowaniu / osobie, która dołączyła do mojej grupy.

Powiadomienia: lekki fragment co NOTIFY_SECONDS porównuje stan ze stanem z ostatniego pełnego reruna.
Zmiana z zewnątrz (inna karta) -> toast + pełny rerun, żeby licznik w pasku i panel wydarzenia
pokazały nowy stan. Własne akcje nie wywołują dodatkowego reruna (pełny rerun zapisuje stan od nowa).
"""

from __future__ import annotations

import streamlit as st

from m5_chat.chat_view import render_dm_list
from m5_chat.group_view import open_group, popover_heading
from m5_chat.groups import group_id_of_room, received_invites, votes_awaiting
from m5_chat.service import escape_markdown, room_title
from shared import state
from shared.models import EventGroup, User, group_room_id
from shared.state import View
from shared.storage import Storage

INBOX_KEY = "m5_inbox"                 # stan popovera (True = otwarty)
NOTIFY_SECONDS = 5.0


def inbox_count(storage: Storage, user_id: str) -> int:
    """Ile spraw czeka na mnie: zaproszenia do grup + głosowania, w których nie oddałem głosu."""
    return len(received_invites(storage, user_id)) + len(votes_awaiting(storage, user_id))


def _close_inbox() -> None:
    st.session_state[INBOX_KEY] = False


def _sync_inbox(user_id: str) -> None:
    """Zamyka skrzynkę po zmianie osoby, widoku albo pokoju (klik w pozycję otwiera czat)."""
    context = (user_id, state.current_view(), state.chat_room_id())
    if st.session_state.get("m5_inbox_ctx") != context:
        st.session_state["m5_inbox_ctx"] = context
        _close_inbox()


def _title(storage: Storage, group_id: str) -> str:
    return escape_markdown(room_title(storage, group_room_id(group_id)))


def _name(storage: Storage, user_id: str) -> str:
    user = storage.get_user(user_id)
    return escape_markdown(user.name if user else "Ktoś")


def _item(label: str, key: str, group: EventGroup, icon: str) -> None:
    st.button(label, key=key, icon=f":material/{icon}:", type="tertiary", width="stretch",
              on_click=open_group, args=(group.id, group.event_id))


def render_inbox(storage: Storage, user: User) -> None:
    _sync_inbox(user.id)
    invites, votes = received_invites(storage, user.id), votes_awaiting(storage, user.id)
    groups = storage.list_member_groups(user.id)
    waiting = len(invites) + len(votes)
    label = f"Ekipy · {waiting}" if waiting else "Ekipy"
    with (
        st.popover(label, icon=":material/groups:", key=INBOX_KEY, on_change="rerun",
                   type="primary" if waiting else "secondary"),
        st.container(key="m5_pop_inbox", gap=None),
    ):
        if invites:
            popover_heading("Zaproszenia")
        for group, invite in invites:
            _item(f"**{_name(storage, invite.invited_by)}** zaprasza: {_title(storage, group.id)}",
                  f"m5_inbox_inv_{group.id}", group, "mail")
        if votes:
            popover_heading("Czekają na Twój głos")
        for group, invite in votes:
            _item(f"{_name(storage, invite.user_id)} → {_title(storage, group.id)}",
                  f"m5_inbox_vote_{invite.id}", group, "how_to_vote")
        popover_heading("Twoje grupy")
        if not groups:
            st.caption("Brak grup — otwórz wydarzenie i zaproś kogoś z listy „Idą” albo „Pasujące osoby”.")
        for group in groups:
            _item(f"{_title(storage, group.id)} · {len(group.members)}", f"m5_inbox_grp_{group.id}",
                  group, "forum")
        popover_heading("Prywatne rozmowy")
        render_dm_list(storage, user, limit=5)


# --------------------------------------------------------------------------- #
# Powiadomienia (toast) o zmianach z innych kart
# --------------------------------------------------------------------------- #

def _watch_state(storage: Storage, user_id: str) -> frozenset[tuple[str, str, str]]:
    items = {("invite", g.id, i.id) for g, i in received_invites(storage, user_id)}
    items |= {("vote", g.id, i.id) for g, i in votes_awaiting(storage, user_id)}
    items |= {("member", g.id, m) for g in storage.list_member_groups(user_id) for m in g.members
              if m != user_id}
    return frozenset(items)


def _news(
    storage: Storage, new_items: set[tuple[str, str, str]], open_group_id: str | None,
) -> list[tuple[str, str]]:
    """(tekst, ikona) toastów o nowościach; pomija grupę, której czat jest właśnie otwarty."""
    toasts = []
    for kind, group_id, ref in sorted(new_items):
        group = storage.get_group(group_id)
        if group is None or group_id == open_group_id:       # otwarty czat pokazuje to sam
            continue
        title = _title(storage, group_id)
        if kind == "invite" and (invite := next((i for i in group.invites if i.id == ref), None)):
            inviter = _name(storage, invite.invited_by)
            toasts.append((f"{inviter} zaprasza Cię do ekipy: {title}", ":material/mail:"))
        elif kind == "vote" and (invite := next((i for i in group.invites if i.id == ref), None)):
            toasts.append((f"Głosowanie w grupie {title}: zaproszenie dla {_name(storage, invite.user_id)}",
                           ":material/how_to_vote:"))
        elif kind == "member":
            toasts.append((f"{_name(storage, ref)} dołącza do Twojej grupy: {title}", ":material/group_add:"))
    return toasts


def render_group_notifier(storage: Storage, user: User) -> None:
    """Wołać raz na przebieg (app.py). Nic nie rysuje poza toastami."""
    for text, icon in st.session_state.pop("m5_toasts", []):
        st.toast(text, icon=icon)
    key = f"m5_watch_{user.id}"
    st.session_state[key] = _watch_state(storage, user.id)     # pełny rerun pokazuje już aktualny stan

    @st.fragment(run_every=NOTIFY_SECONDS)
    def _watch() -> None:
        current, previous = _watch_state(storage, user.id), st.session_state.get(key, frozenset())
        if current == previous:
            return
        st.session_state[key] = current
        open_group_id = group_id_of_room(state.chat_room_id()) if state.current_view() is View.CHAT else None
        st.session_state["m5_toasts"] = _news(storage, set(current - previous), open_group_id)
        st.rerun()

    _watch()
