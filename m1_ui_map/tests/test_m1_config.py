"""M1-01 — konfiguracja Streamlit: zepsuty config.toml wywraca `streamlit run` całemu zespołowi."""

import re
import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[2] / ".streamlit" / "config.toml"


def test_streamlit_config_is_valid_toml():
    config = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", config["theme"]["primaryColor"])
    assert config["browser"]["gatherUsageStats"] is False
