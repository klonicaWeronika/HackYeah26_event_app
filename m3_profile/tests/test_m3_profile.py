"""M3 — testy profilu (logika + bezpieczeństwo HTML)."""

from m3_profile.views import avatar_html, user_card_html
from shared.models import MatchResult, User
from shared.storage import Storage


def test_avatar_html_escapes_user_content():
    evil = User(id="u_x", name='<script>alert(1)</script>', avatar_url='x" onerror="alert(1)')
    html = avatar_html(evil)
    assert "<script>" not in html and 'onerror="' not in html


def test_avatar_fallback_uses_initials():
    assert "AN" in avatar_html(User(id="u_y", name="Anna Nowak"))


def test_profile_update_roundtrip(storage: Storage, demo_user: User):
    storage.upsert_user(demo_user.copy_with(bio="Nowe bio", tags=["Teatr", "jazz"]))
    saved = storage.get_user(demo_user.id)
    assert saved.bio == "Nowe bio" and saved.tags == ["teatr", "jazz"]


# --------------------------------------------------------------------------- #
# M3-05: HTML karty osoby
# --------------------------------------------------------------------------- #

def _match(user: User, score=0.42, shared=("jazz",), reason="Oboje lubicie: jazz") -> MatchResult:
    return MatchResult(user=user, event_id="e1", score=score, shared_tags=list(shared), reason=reason)


def test_card_html_escapes_all_user_and_matching_content():
    evil = User(id="u_x", name="<b>Zła</b>", bio="<img src=x onerror=alert(1)>",
                tags=["<script>", "jazz"], avatar_url='x" onerror="alert(1)')
    out = user_card_html(evil, _match(evil, shared=["<script>"], reason="<i>uzasadnienie</i>"))
    for raw in ("<b>", "<script>", "<i>", "<img src=x", 'onerror="'):
        assert raw not in out, raw
    assert "&lt;b&gt;Zła&lt;/b&gt;" in out
    assert "&lt;img" not in user_card_html(evil, _match(evil))   # jest uzasadnienie M4 -> zamiast bio
    assert "&lt;img" in user_card_html(evil)                     # bez dopasowania: bio (escapowane)


def test_card_shows_shared_tags_first_and_highlighted():
    user = User(id="u_x", name="Bartek", tags=["klasyka", "jazz", "wino", "fotografia"])
    out = user_card_html(user, _match(user, shared=["jazz", "fotografia"]))
    assert out.count("✓ ") == 2 and out.count('title="Wspólne zainteresowanie"') == 2
    order = [out.index(t) for t in ("✓ jazz", "✓ fotografia", ">klasyka<", ">wino<")]
    assert order == sorted(order), "wspólne tagi na początku"


def test_card_score_badge_and_bar():
    user = User(id="u_x", name="Ania", tags=["jazz"])
    out = user_card_html(user, _match(user, score=0.42))
    assert ">42%<" in out and "width:42%" in out and 'aria-label="Dopasowanie 42%"' in out
    assert "width:3%" in user_card_html(user, _match(user, score=0.0, shared=()))   # pasek zawsze widoczny
    assert "Dopasowanie" not in user_card_html(user)                              # bez wyniku -> bez paska


def test_card_limits_tag_chips():
    user = User(id="u_x", name="Ania", tags=[f"tag{i}" for i in range(9)])
    out = user_card_html(user)
    assert ">tag5<" in out and ">tag6<" not in out and ">+3<" in out


def test_card_shortens_long_text_and_has_no_newlines():
    user = User(id="u_x", name="Ania", bio="słowo " * 60)
    out = user_card_html(user)
    assert "…" in out and "słowo " * 20 not in out
    assert "\n" not in out, "wcięty/łamany HTML markdown zamienia na blok kodu"


# --------------------------------------------------------------------------- #
# M3-06: HTML podglądu profilu
# --------------------------------------------------------------------------- #

def test_profile_header_escapes_and_keeps_bio_lines_without_newlines():
    from m3_profile.views import _profile_header_html

    evil = User(id="u_x", name="<b>Zła</b>", bio="Linia 1\n\n<script>alert(1)</script>\n**gruby**")
    out = _profile_header_html(evil, "Macie <i>coś</i>")
    assert "<b>" not in out and "<script>" not in out and "<i>" not in out
    assert "\n" not in out and out.count("<br>") == 3       # pusta linia nie zamyka bloku HTML w markdownie


def test_event_row_escapes_title_and_venue():
    from datetime import datetime

    from m3_profile.views import _event_row_html
    from shared.models import Event

    event = Event(id="e", title="<img src=x onerror=alert(1)>", venue="<b>Klub</b>",
                  start=datetime(2030, 1, 1, 20), lat=50.06, lon=19.94)
    out = _event_row_html(event, hidden=True)
    assert "<img" not in out and "<b>Klub" not in out and "ukryte w dopasowaniach" in out
