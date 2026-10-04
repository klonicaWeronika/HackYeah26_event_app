"""
M5 — grupy na wydarzenia („ekipy”): logika bez streamlit (testowalna pytestem).

Skąd się biorą: „Dodaj do ekipy” na karcie pasującej osoby albo lista „Idą / Interesuje ich” przy wydarzeniu
-> zaproszenie do MOJEJ grupy na to wydarzenie (grupa powstaje przy pierwszym zaproszeniu).
Czat otwierany z profilu to dalej zwykły DM (`dm_room_id`) — bez kontekstu wydarzenia.

Zasady:
  * Jedna osoba = najwyżej jedna grupa na wydarzenie; przyjęcie innego zaproszenia = wyjście z obecnej.
  * Zaproszenie musi zatwierdzić KAŻDY członek (głosowanie na czacie). Zapraszający jest „za” od razu,
    więc w jednoosobowej grupie zaproszenie wychodzi natychmiast. Jeden głos „przeciw” = odrzucone.
  * Zaproszona osoba widzi czat grupy (tylko do odczytu) i może dołączyć albo odrzucić.
  * Grupę można opuścić; ostatnia osoba zamyka grupę. Wyjście członka przelicza otwarte głosowania.

Publiczne API:
    group_id_of_room(room_id) -> str | None
    role_in(group, user_id) -> GroupRole
    member_group(storage, event_id, user_id) -> EventGroup | None
    received_invites(storage, user_id, *, event_id=None) -> list[tuple[EventGroup, GroupInvite]]
    votes_awaiting(storage, user_id) -> list[tuple[EventGroup, GroupInvite]]
    invite_candidates(storage, event_id, me_id, group=None) -> list[tuple[User, AttendanceStatus]]
    invite(storage, event_id, inviter_id, invitee_id) -> InviteResult | None
    vote(storage, group_id, invite_id, voter_id, approve) -> VoteResult
    accept_invite(storage, group_id, user_id) -> EventGroup | None
    decline_invite(storage, group_id, user_id) -> bool
    leave_group(storage, group_id, user_id) -> bool
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from shared.models import (
    AttendanceStatus, ChatMessage, EventGroup, GroupInvite, MessageKind, User, group_room_id, now,
)
from shared.storage import Storage

SYSTEM_USER_ID = "system"           # autor komunikatów grupy (dołączenia, wyniki głosowań)


class GroupRole(str, Enum):
    MEMBER = "member"               # pisze na czacie, głosuje, zaprasza
    INVITED = "invited"             # wysłane zaproszenie: czyta czat, może dołączyć albo odrzucić
    NONE = "none"                   # brak dostępu (także zaproszenie, nad którym grupa jeszcze głosuje)


class InviteStatus(str, Enum):
    SENT = "sent"                   # zaproszenie od razu trafiło do osoby (byłem sam w grupie)
    VOTING = "voting"               # czeka na głosy pozostałych członków
    ALREADY_INVITED = "already_invited"
    ALREADY_MEMBER = "already_member"


class VoteResult(str, Enum):
    COUNTED = "counted"             # głos policzony, czekamy na resztę
    SENT = "sent"                   # komplet głosów „za” -> zaproszenie wysłane
    REJECTED = "rejected"           # głos „przeciw” -> zaproszenie przepada
    IGNORED = "ignored"             # już głosował / nie jest członkiem / głosowanie zakończone


@dataclass(frozen=True)
class InviteResult:
    group: EventGroup
    invite: GroupInvite | None      # None przy ALREADY_MEMBER
    status: InviteStatus


# --------------------------------------------------------------------------- #
# Odczyt
# --------------------------------------------------------------------------- #

def group_id_of_room(room_id: str | None) -> str | None:
    kind, _, rest = (room_id or "").partition(":")
    return rest if kind == "group" and rest else None


def role_in(group: EventGroup | None, user_id: str) -> GroupRole:
    if group is None:
        return GroupRole.NONE
    if user_id in group.members:
        return GroupRole.MEMBER
    invite = group.invite_for(user_id)
    return GroupRole.INVITED if invite is not None and invite.is_sent else GroupRole.NONE


def member_group(storage: Storage, event_id: str, user_id: str) -> EventGroup | None:
    """Moja grupa na to wydarzenie (najwyżej jedna)."""
    return next((g for g in storage.list_member_groups(user_id) if g.event_id == event_id), None)


def received_invites(
    storage: Storage, user_id: str, *, event_id: str | None = None
) -> list[tuple[EventGroup, GroupInvite]]:
    """Wysłane do mnie zaproszenia (po głosowaniu grupy), od najświeższego."""
    found = []
    for group in storage.list_invited_groups(user_id):
        invite = group.invite_for(user_id)
        if invite and invite.is_sent and user_id not in group.members and event_id in (None, group.event_id):
            found.append((group, invite))
    found.sort(key=lambda pair: pair[1].sent_at, reverse=True)
    return found


def votes_awaiting(storage: Storage, user_id: str) -> list[tuple[EventGroup, GroupInvite]]:
    """Głosowania w moich grupach, w których jeszcze nie oddałem głosu."""
    return [
        (group, invite)
        for group in storage.list_member_groups(user_id)
        for invite in group.invites
        if not invite.is_sent and user_id not in invite.approvals
    ]


def invite_candidates(
    storage: Storage, event_id: str, me_id: str, group: EventGroup | None = None
) -> list[tuple[User, AttendanceStatus]]:
    """Lista „Idą + Interesuje mnie” do zaproszenia: zapisani, którzy zgodzili się na dopasowania.

    Bez mnie, członków grupy i osób już zaproszonych (także w trakcie głosowania). Najpierw „Idę”.
    """
    taken = {me_id, *(group.members if group else ()), *(i.user_id for i in (group.invites if group else ()))}
    statuses = {a.user_id: a.status for a in storage.list_attendees(event_id)
                if a.open_to_meet and a.user_id not in taken}
    users = storage.get_users(statuses)
    order = list(AttendanceStatus)
    people = [(users[uid], status) for uid, status in statuses.items() if uid in users]
    people.sort(key=lambda p: (order.index(p[1]), p[0].name.lower()))
    return people


# --------------------------------------------------------------------------- #
# Zmiany (każda przez Storage.update_group -> atomowo; komunikaty na czacie po zapisie)
# --------------------------------------------------------------------------- #

def _name(storage: Storage, user_id: str) -> str:
    user = storage.get_user(user_id)
    return user.name if user else "Ktoś"


def _post(storage: Storage, group_id: str, text: str, *, kind: MessageKind = MessageKind.SYSTEM,
          ref: str | None = None) -> ChatMessage:
    return storage.add_message(ChatMessage(
        room_id=group_room_id(group_id), user_id=SYSTEM_USER_ID, text=text, kind=kind, ref=ref,
    ))


def _send_ready(group: EventGroup) -> tuple[EventGroup, list[GroupInvite]]:
    """Głosowania z kompletem głosów „za” -> zaproszenia wysłane. Zwraca grupę i świeżo wysłane."""
    members, stamp = set(group.members), now()
    invites, sent = [], []
    for invite in group.invites:
        if not invite.is_sent and members <= set(invite.approvals):
            invite = invite.copy_with(sent_at=stamp)
            sent.append(invite)
        invites.append(invite)
    return group.copy_with(invites=invites), sent


def _announce_sent(storage: Storage, group_id: str, sent: list[GroupInvite]) -> None:
    for invite in sent:
        _post(storage, group_id, f"Wszyscy za ✅ — zaproszenie wysłane: {_name(storage, invite.user_id)}")


def invite(storage: Storage, event_id: str, inviter_id: str, invitee_id: str) -> InviteResult | None:
    """Zaproś osobę do mojej grupy na wydarzenie (grupa powstaje, jeśli jej nie mam).

    None: zaproszenie samego siebie, nieznana osoba albo wydarzenie.
    """
    if inviter_id == invitee_id or storage.get_event(event_id) is None or not storage.get_user(invitee_id):
        return None
    group = member_group(storage, event_id, inviter_id) or storage.upsert_group(
        EventGroup(event_id=event_id, members=[inviter_id], created_by=inviter_id)
    )
    outcome: dict = {}

    def change(g: EventGroup) -> EventGroup:
        if invitee_id in g.members:
            outcome.update(status=InviteStatus.ALREADY_MEMBER, invite=None)
            return g
        if (existing := g.invite_for(invitee_id)) is not None:
            outcome.update(status=InviteStatus.ALREADY_INVITED, invite=existing)
            return g
        new = GroupInvite(user_id=invitee_id, invited_by=inviter_id, approvals=[inviter_id])
        g, sent = _send_ready(g.copy_with(invites=[*g.invites, new]))
        status = InviteStatus.SENT if sent else InviteStatus.VOTING
        outcome.update(status=status, invite=g.invite_for(invitee_id))
        return g

    group = storage.update_group(group.id, change)
    if group is None:                       # grupa zniknęła w międzyczasie (ostatnia osoba wyszła)
        return None
    status, created = outcome["status"], outcome["invite"]
    if status in (InviteStatus.SENT, InviteStatus.VOTING):
        verb = "zaprasza do grupy" if status is InviteStatus.SENT else "chce zaprosić do grupy"
        text = f"{_name(storage, inviter_id)} {verb}: {_name(storage, invitee_id)}"
        _post(storage, group.id, text, kind=MessageKind.VOTE, ref=created.id)
    return InviteResult(group, created, status)


def vote(storage: Storage, group_id: str, invite_id: str, voter_id: str, approve: bool) -> VoteResult:
    """Głos członka grupy w sprawie zaproszenia. Jeden głos „przeciw” odrzuca zaproszenie."""
    outcome: dict = {"result": VoteResult.IGNORED}

    def change(g: EventGroup) -> EventGroup:
        invite = next((i for i in g.invites if i.id == invite_id), None)
        if invite is None or invite.is_sent or voter_id not in g.members or voter_id in invite.approvals:
            return g
        outcome["invite"] = invite
        if not approve:
            outcome["result"] = VoteResult.REJECTED
            return g.copy_with(invites=[i for i in g.invites if i.id != invite_id])
        g, sent = _send_ready(g.copy_with(invites=[
            i.copy_with(approvals=[*i.approvals, voter_id]) if i.id == invite_id else i for i in g.invites
        ]))
        outcome["result"] = VoteResult.SENT if any(i.id == invite_id for i in sent) else VoteResult.COUNTED
        return g

    storage.update_group(group_id, change)
    result = outcome["result"]
    if result is VoteResult.REJECTED:
        voter, invitee = _name(storage, voter_id), _name(storage, outcome["invite"].user_id)
        _post(storage, group_id, f"{voter} jest przeciw — zaproszenie odrzucone: {invitee}")
    elif result is VoteResult.SENT:
        _announce_sent(storage, group_id, [outcome["invite"]])
    return result


def accept_invite(storage: Storage, group_id: str, user_id: str) -> EventGroup | None:
    """Dołącz do grupy z wysłanego zaproszenia; z dotychczasowej grupy na to wydarzenie wychodzę."""
    group = storage.get_group(group_id)
    if role_in(group, user_id) is not GroupRole.INVITED:
        return None
    current = member_group(storage, group.event_id, user_id)
    if current is not None:
        leave_group(storage, current.id, user_id)
    outcome: dict = {"joined": False}

    def change(g: EventGroup) -> EventGroup:
        if role_in(g, user_id) is not GroupRole.INVITED:
            return g
        outcome["joined"] = True
        invites = [i for i in g.invites if i.user_id != user_id]
        return g.copy_with(members=[*g.members, user_id], invites=invites)

    group = storage.update_group(group_id, change)
    if not outcome["joined"]:
        return None
    _post(storage, group_id, f"{_name(storage, user_id)} dołącza do grupy 👋")
    return group


def decline_invite(storage: Storage, group_id: str, user_id: str) -> bool:
    outcome: dict = {"declined": False}

    def change(g: EventGroup) -> EventGroup:
        if role_in(g, user_id) is not GroupRole.INVITED:
            return g
        outcome["declined"] = True
        return g.copy_with(invites=[i for i in g.invites if i.user_id != user_id])

    storage.update_group(group_id, change)
    if outcome["declined"]:
        _post(storage, group_id, f"{_name(storage, user_id)} odrzuca zaproszenie")
    return outcome["declined"]


def leave_group(storage: Storage, group_id: str, user_id: str) -> bool:
    """Wyjście z grupy. Ostatnia osoba zamyka grupę; głosowania czekające tylko na mnie -> wysłane."""
    outcome: dict = {"left": False, "sent": []}

    def change(g: EventGroup) -> EventGroup | None:
        if user_id not in g.members:
            return g
        outcome["left"] = True
        members = [m for m in g.members if m != user_id]
        if not members:
            return None
        g, outcome["sent"] = _send_ready(g.copy_with(members=members, invites=[
            i.copy_with(approvals=[a for a in i.approvals if a != user_id]) for i in g.invites
        ]))
        return g

    remaining = storage.update_group(group_id, change)
    if outcome["left"] and remaining is not None:
        _post(storage, group_id, f"{_name(storage, user_id)} opuszcza grupę")
        _announce_sent(storage, group_id, outcome["sent"])
    return outcome["left"]
