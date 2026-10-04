"""M5 — grupy na wydarzenia („ekipy”): zaproszenia, głosowania, dołączanie, wychodzenie (logika, bez UI)."""

from m5_chat.groups import (
    SYSTEM_USER_ID, GroupRole, InviteStatus, VoteResult, accept_invite, decline_invite, invite,
    invite_candidates, leave_group, member_group, received_invites, role_in, vote, votes_awaiting,
)
from m5_chat.service import can_post, send_message
from shared.models import AttendanceStatus, MessageKind, group_room_id
from shared.storage import Storage

JAZZ = "e_jazz_alchemia"     # mocki: ekipa g_jazz = Kuba, Bartek, Natalia; Ola ma zaproszenie od Kuby
REJS = "e_rejs_kino"         # zapisani: Tomek, Marta, Ola, Kuba — bez grup


def _notices(storage: Storage, group_id: str) -> list[tuple[MessageKind, str]]:
    messages = storage.list_messages(group_room_id(group_id))
    return [(m.kind, m.text) for m in messages if m.user_id == SYSTEM_USER_ID]


def _last_notice(storage: Storage, group_id: str) -> str:
    kind, text = _notices(storage, group_id)[-1]
    assert kind is MessageKind.SYSTEM
    return text


def test_seeded_invite_is_read_only_until_accepted(storage: Storage):
    group = storage.get_group("g_jazz")
    assert member_group(storage, JAZZ, "u_kuba") == group
    assert [(g.id, i.invited_by) for g, i in received_invites(storage, "u_ola")] == [("g_jazz", "u_kuba")]
    assert role_in(group, "u_ola") is GroupRole.INVITED
    assert send_message(storage, group_room_id("g_jazz"), "u_ola", "hej") is None
    assert accept_invite(storage, "g_jazz", "u_ola").members == ["u_kuba", "u_bartek", "u_natalia", "u_ola"]
    assert send_message(storage, group_room_id("g_jazz"), "u_ola", "hej") is not None
    assert received_invites(storage, "u_ola") == []
    assert _notices(storage, "g_jazz")[-1] == (MessageKind.SYSTEM, "Ola dołącza do grupy 👋")


def test_first_invite_creates_my_group_and_is_sent_at_once(storage: Storage):
    result = invite(storage, REJS, "u_ola", "u_tomek")
    assert result.status is InviteStatus.SENT and result.invite.is_sent
    assert result.group.members == ["u_ola"] and result.group.created_by == "u_ola"
    assert member_group(storage, REJS, "u_ola") == result.group
    assert role_in(result.group, "u_tomek") is GroupRole.INVITED
    card = storage.list_messages(group_room_id(result.group.id))[-1]
    assert (card.kind, card.ref) == (MessageKind.VOTE, result.invite.id)
    assert card.text == "Ola zaprasza do grupy: Tomek"


def test_invite_in_bigger_group_needs_a_yes_from_every_member(storage: Storage):
    result = invite(storage, JAZZ, "u_kuba", "u_tomek")
    assert result.status is InviteStatus.VOTING and result.invite.approvals == ["u_kuba"]
    assert role_in(result.group, "u_tomek") is GroupRole.NONE            # nic nie widzi przed głosowaniem
    assert received_invites(storage, "u_tomek") == []
    assert [i.user_id for _, i in votes_awaiting(storage, "u_bartek")] == ["u_tomek"]
    assert votes_awaiting(storage, "u_kuba") == []

    assert vote(storage, "g_jazz", result.invite.id, "u_bartek", True) is VoteResult.COUNTED
    assert vote(storage, "g_jazz", result.invite.id, "u_natalia", True) is VoteResult.SENT
    assert role_in(storage.get_group("g_jazz"), "u_tomek") is GroupRole.INVITED
    assert _last_notice(storage, "g_jazz") == "Wszyscy za ✅ — zaproszenie wysłane: Tomek"


def test_one_no_vote_rejects_the_invite(storage: Storage):
    result = invite(storage, JAZZ, "u_kuba", "u_tomek")
    assert vote(storage, "g_jazz", result.invite.id, "u_natalia", False) is VoteResult.REJECTED
    assert storage.get_group("g_jazz").invite_for("u_tomek") is None
    assert _last_notice(storage, "g_jazz") == "Natalia jest przeciw — zaproszenie odrzucone: Tomek"
    # odrzucona osoba może zostać zaproszona ponownie (nowe głosowanie)
    assert invite(storage, JAZZ, "u_bartek", "u_tomek").status is InviteStatus.VOTING


def test_votes_that_do_not_count(storage: Storage):
    result = invite(storage, JAZZ, "u_kuba", "u_tomek")
    invite_id = result.invite.id
    assert vote(storage, "g_jazz", invite_id, "u_kuba", True) is VoteResult.IGNORED     # zapraszający: już za
    assert vote(storage, "g_jazz", invite_id, "u_ola", False) is VoteResult.IGNORED     # nie jest członkiem
    assert vote(storage, "g_jazz", "inv_nieznane", "u_bartek", True) is VoteResult.IGNORED
    assert vote(storage, "g_jazz", invite_id, "u_bartek", True) is VoteResult.COUNTED
    assert vote(storage, "g_jazz", invite_id, "u_bartek", False) is VoteResult.IGNORED  # głos się nie zmienia
    assert storage.get_group("g_jazz").invite_for("u_tomek").approvals == ["u_kuba", "u_bartek"]


def test_inviting_members_invited_people_or_myself_changes_nothing(storage: Storage):
    assert invite(storage, JAZZ, "u_kuba", "u_bartek").status is InviteStatus.ALREADY_MEMBER
    assert invite(storage, JAZZ, "u_kuba", "u_ola").status is InviteStatus.ALREADY_INVITED
    assert invite(storage, JAZZ, "u_kuba", "u_kuba") is None
    assert invite(storage, JAZZ, "u_kuba", "u_nieznany") is None
    assert invite(storage, "e_nieznane", "u_kuba", "u_ola") is None
    assert len(storage.get_group("g_jazz").invites) == 1


def test_one_group_per_event_accepting_leaves_my_current_group(storage: Storage):
    mine = invite(storage, JAZZ, "u_ola", "u_tomek").group                # Ola zakłada własną ekipę na jazz
    assert accept_invite(storage, "g_jazz", "u_ola") is not None          # ...i przyjmuje zaproszenie Kuby
    assert member_group(storage, JAZZ, "u_ola").id == "g_jazz"
    assert storage.get_group(mine.id) is None                             # była sama -> grupa zamknięta
    assert received_invites(storage, "u_tomek") == []
    assert [g.id for g in storage.list_member_groups("u_ola") if g.event_id == JAZZ] == ["g_jazz"]


def test_napisz_again_in_my_group_proposes_instead_of_new_group(storage: Storage):
    first = invite(storage, REJS, "u_ola", "u_tomek")
    accept_invite(storage, first.group.id, "u_tomek")
    second = invite(storage, REJS, "u_ola", "u_marta")
    assert second.group.id == first.group.id and second.status is InviteStatus.VOTING
    assert len(storage.list_groups(REJS)) == 1


def test_decline_removes_invite(storage: Storage):
    assert decline_invite(storage, "g_jazz", "u_ola")
    assert role_in(storage.get_group("g_jazz"), "u_ola") is GroupRole.NONE
    assert not decline_invite(storage, "g_jazz", "u_ola")
    assert accept_invite(storage, "g_jazz", "u_ola") is None
    assert _last_notice(storage, "g_jazz") == "Ola odrzuca zaproszenie"


def test_leaving_recounts_votes_and_last_member_closes_group(storage: Storage):
    pending = invite(storage, "e_planszowki", "u_michal", "u_kuba")      # g_planszowki: Michał, Lukas
    assert pending.status is InviteStatus.VOTING
    assert leave_group(storage, "g_planszowki", "u_lukas")
    group = storage.get_group("g_planszowki")
    assert group.members == ["u_michal"]
    assert group.invite_for("u_kuba").is_sent                             # brakowało tylko głosu Lukasa
    assert [text for _, text in _notices(storage, "g_planszowki")[-2:]] == [
        "Lukas opuszcza grupę", "Wszyscy za ✅ — zaproszenie wysłane: Kuba",
    ]
    assert not can_post(storage, group_room_id("g_planszowki"), "u_lukas")
    assert not leave_group(storage, "g_planszowki", "u_lukas")
    assert leave_group(storage, "g_planszowki", "u_michal")
    assert storage.get_group("g_planszowki") is None
    assert received_invites(storage, "u_kuba") == []


def test_invite_candidates_are_going_then_interested_without_taken_people(storage: Storage):
    storage.join_event("u_marta", JAZZ, status=AttendanceStatus.INTERESTED)
    storage.join_event("u_zosia", JAZZ, status=AttendanceStatus.INTERESTED, open_to_meet=False)   # ukryta
    group = storage.get_group("g_jazz")
    people = invite_candidates(storage, JAZZ, "u_kuba", group)
    assert [(u.id, s) for u, s in people] == [
        ("u_tomek", AttendanceStatus.GOING), ("u_marta", AttendanceStatus.INTERESTED),
    ]
    # bez grupy: wszyscy widoczni zapisani poza mną
    assert [u.id for u, _ in invite_candidates(storage, JAZZ, "u_ola")] == [
        "u_bartek", "u_kuba", "u_natalia", "u_tomek", "u_marta",
    ]
