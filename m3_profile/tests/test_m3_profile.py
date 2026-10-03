"""M3 — testy profilu (logika + bezpieczeństwo HTML)."""

from m3_profile.views import avatar_html
from shared.models import User
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
