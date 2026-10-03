"""M1-01 — konfiguracja Streamlit: zepsuty config.toml wywraca `streamlit run` całemu zespołowi."""

import re
import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[2] / ".streamlit" / "config.toml"


def test_streamlit_config_is_valid_toml():
    config = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    theme = config["theme"]
    # Kolor marki w obu motywach (sekcje light/dark -> aplikacja podąża za motywem systemu).
    colors = {theme[mode]["primaryColor"] for mode in ("light", "dark")}
    assert len(colors) == 1 and re.fullmatch(r"#[0-9A-Fa-f]{6}", colors.pop())
    assert "primaryColor" not in theme, "kolor w [theme] wymusza jasny motyw własny"
    assert config["client"]["toolbarMode"] == "minimal"
    assert config["browser"]["gatherUsageStats"] is False
