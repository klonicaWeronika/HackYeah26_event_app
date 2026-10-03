"""
M1 — wygląd aplikacji: mapa na cały ekran, pływające panele, górny pasek z wyszukiwarką.

Pozycjonowanie opiera się na klasach `st-key-<klucz>` kontenerów Streamlita (stabilne, nadawane z Pythona).
Kolory w zmiennych CSS (`--krk-*`) w dwóch wariantach: jasnym i ciemnym (wg `st.context.theme`).
Chowanie paneli: ukryty checkbox + `:has(input:checked)` -> animacja startuje od razu po kliknięciu,
bez czekania na rerun.
"""

from __future__ import annotations

from collections.abc import Iterable

from m1_ui_map.map_view import CATEGORY_COLORS
from shared.models import Category

TOPBAR_H = 64           # px — górny pasek (logo, wyszukiwarka, akcje)
CATBAR_H = 84           # px — pasek kategorii
LEFT_W = "clamp(400px, 28vw, 480px)"       # lista wydarzeń
RIGHT_W = "clamp(380px, 26vw, 460px)"      # szczegóły wydarzenia
SHEET_W = 640                              # px — czat / profil / formularz w arkuszu nad listą
GAP = 16                # px — odstęp paneli od krawędzi ekranu

_TOKENS = {
    False: """
  --krk-surface: rgba(255, 255, 255, 0.94);
  --krk-surface-solid: #FFFFFF;
  --krk-glass: rgba(255, 255, 255, 0.82);
  --krk-soft: #F4F5F7;
  --krk-soft-2: #ECEEF2;
  --krk-line: rgba(15, 23, 42, 0.08);
  --krk-line-strong: rgba(15, 23, 42, 0.14);
  --krk-text: #0F172A;
  --krk-muted: #64748B;
  --krk-faint: #94A3B8;
  --krk-price: #16A34A;
  --krk-shadow: 0 18px 50px -20px rgba(15, 23, 42, 0.35), 0 2px 8px rgba(15, 23, 42, 0.06);
  --krk-shadow-sm: 0 6px 18px -10px rgba(15, 23, 42, 0.30), 0 1px 3px rgba(15, 23, 42, 0.05);
""",
    True: """
  --krk-surface: rgba(20, 23, 31, 0.94);
  --krk-surface-solid: #161922;
  --krk-glass: rgba(20, 23, 31, 0.80);
  --krk-soft: rgba(255, 255, 255, 0.05);
  --krk-soft-2: rgba(255, 255, 255, 0.09);
  --krk-line: rgba(255, 255, 255, 0.08);
  --krk-line-strong: rgba(255, 255, 255, 0.16);
  --krk-text: #F1F5F9;
  --krk-muted: #94A3B8;
  --krk-faint: #64748B;
  --krk-price: #4ADE80;
  --krk-shadow: 0 18px 50px -18px rgba(0, 0, 0, 0.75), 0 2px 8px rgba(0, 0, 0, 0.35);
  --krk-shadow-sm: 0 6px 18px -10px rgba(0, 0, 0, 0.7), 0 1px 3px rgba(0, 0, 0, 0.3);
""",
}

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap');
:root {
  --krk-primary: #E4572E;
  --krk-primary-2: #D9431A;
  --krk-primary-soft: rgba(228, 87, 46, 0.12);
  --krk-grad: linear-gradient(135deg, #F2784B 0%, #E4572E 45%, #C2185B 100%);
  --krk-topbar: __TOPBAR__px;
  --krk-catbar: __CATBAR__px;
  --krk-top: calc(var(--krk-topbar) + var(--krk-catbar) + var(--krk-gap));
  --krk-gap: __GAP__px;
  --krk-radius: 18px;
  --krk-left-w: __LEFT_W__;
  --krk-right-w: __RIGHT_W__;
__TOKENS__
}

/* ============ Chrome Streamlita: bez nagłówka, sidebara i marginesów ============ */
header[data-testid="stHeader"], [data-testid="stDecoration"], [data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"], [data-testid="stStatusWidget"] {display: none !important;}
[data-testid="stMain"] {overflow: hidden;}
[data-testid="stMainBlockContainer"] {padding: 0 !important; max-width: none !important;}
.stApp {background: var(--krk-soft);}
/* Reruny nie przyciemniają paneli. */
.stale-element, [data-stale="true"] {opacity: 1 !important; transition: none !important;}
.material-ico {
  font-family: "Material Symbols Rounded"; font-weight: normal; font-style: normal; line-height: 1;
  letter-spacing: normal; text-transform: none; white-space: nowrap; direction: ltr;
  -webkit-font-smoothing: antialiased; font-variation-settings: "FILL" 0, "wght" 400; display: inline-block;
}

/* ============ Mapa — cały ekran pod wszystkim ============ */
.st-key-m1_map {position: fixed !important; inset: 0; z-index: 0;}
.st-key-m1_map iframe {
  position: fixed; inset: 0; width: 100vw !important; height: 100vh !important; border: 0; display: block;
}

/* ============ Górny pasek ============ */
.st-key-m1_topbar {
  position: fixed !important; top: 0; left: 0; right: 0; z-index: 30; gap: 0 !important;
  background: var(--krk-glass); backdrop-filter: saturate(1.6) blur(18px); -webkit-backdrop-filter: saturate(1.6) blur(18px);
  border-bottom: 1px solid var(--krk-line);
  box-shadow: 0 10px 30px -24px rgba(15, 23, 42, 0.5);
}
.st-key-m1_topbar > [data-testid="stLayoutWrapper"] {flex: 0 0 auto;}
.st-key-m1_topbar_row {
  height: var(--krk-topbar); min-height: var(--krk-topbar); padding: 0 20px; gap: 18px !important; flex-wrap: nowrap !important;
}
.m1-brand {display: flex; align-items: center; gap: 11px; white-space: nowrap; user-select: none;}
.m1-brand img {width: 38px; height: 38px; display: block; filter: drop-shadow(0 6px 12px rgba(228, 87, 46, .35));}
.m1-brand-name {font-size: 1.28rem; font-weight: 800; letter-spacing: -0.03em; color: var(--krk-text); line-height: 1.05;}
.m1-brand-name span {font-weight: 500; margin-left: 4px;}
.m1-brand-tag {
  font-size: 0.72rem; color: var(--krk-muted); letter-spacing: 0.01em; margin-top: 2px;
  font-family: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
}

/* Wyszukiwarka: jedna „pigułka” z polem tekstowym, lokalizacją i przyciskiem. */
[data-testid="stLayoutWrapper"]:has(> .st-key-m1_search) {flex: 0 1 720px; min-width: 360px; margin: 0 auto;}
[data-testid="stLayoutWrapper"]:has(> .st-key-m1_actions) {flex: 0 0 auto;}
.st-key-m1_search {
  flex: 1 1 auto !important; width: 100% !important; height: 50px; padding: 0 5px 0 4px; gap: 0 !important; flex-wrap: nowrap !important;
  background: var(--krk-surface-solid); border-radius: 999px;
  box-shadow: var(--krk-shadow-sm), 0 0 0 1px var(--krk-line);
  transition: box-shadow .2s ease;
}
.st-key-m1_search:focus-within {box-shadow: var(--krk-shadow-sm), 0 0 0 2px var(--krk-primary-soft), 0 0 0 1px var(--krk-primary);}
.st-key-m1_search [data-testid="stTextInput"] {flex: 1 1 auto; min-width: 0;}
.st-key-m1_search [data-testid="stElementContainer"]:has([data-testid="stTextInput"]) {flex: 1 1 auto !important; width: auto !important; min-width: 0;}
.st-key-m1_search [data-baseweb="input"], .st-key-m1_search [data-baseweb="base-input"] {
  background: transparent !important; border: none !important; box-shadow: none !important;
}
.st-key-m1_search input {font-size: 0.95rem; padding-left: 4px;}
.st-key-m1_search input::placeholder {
  color: var(--krk-muted); opacity: 1;
  font-family: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace; font-size: 0.85rem;
}
.st-key-m1_search [data-testid="stTextInput"] > div, .st-key-m1_search [data-testid="stTextInputRootElement"] {
  border: none !important; background: transparent !important;
}
.st-key-m1_search [data-testid="stPopover"] {flex: 0 0 auto;}
.st-key-m1_search [data-testid="stPopover"] button {
  border: none; border-left: 1px solid var(--krk-line); border-radius: 0; background: transparent;
  height: 30px; min-height: 0; padding: 0 14px; color: var(--krk-text); white-space: nowrap; box-shadow: none;
}
.st-key-m1_search [data-testid="stPopover"] button:hover {color: var(--krk-primary);}
.st-key-m1_search_go button {
  width: 40px; height: 40px; min-height: 0; border-radius: 50% !important; padding: 0; border: none;
  background: var(--krk-grad); color: #fff; box-shadow: 0 6px 16px -4px rgba(228, 87, 46, .6);
}
.st-key-m1_search_go button:hover {filter: brightness(1.06); color: #fff;}

/* Akcje po prawej. */
.st-key-m1_actions {gap: 10px !important; flex-wrap: nowrap !important;}
.st-key-m1_add_event_top button {
  border-radius: 999px; height: 40px; min-height: 0; padding: 0 16px; background: var(--krk-surface-solid);
  border: 1px solid var(--krk-line-strong); font-weight: 600; white-space: nowrap;
}
.st-key-m1_add_event_top button:hover {border-color: var(--krk-primary); color: var(--krk-primary);}
.m1-header {display: flex; align-items: center; gap: 10px; padding: 3px 6px 3px 3px; white-space: nowrap;}
.m1-header .m1-hello {font-weight: 650; font-size: 0.92rem; line-height: 1.2; color: var(--krk-text);}
.m1-header .m1-plans {font-size: 0.74rem; color: var(--krk-muted); line-height: 1.2;}
.st-key-m1_actions [data-testid="stPopover"] > div > button, .st-key-m1_actions [data-testid="stPopover"] button {
  height: 40px; min-height: 0; border-radius: 999px; padding: 0 14px; background: var(--krk-text); color: var(--krk-surface-solid);
  border: none; font-weight: 600;
}
.st-key-m1_actions [data-testid="stPopover"] button:hover {filter: brightness(1.15); color: var(--krk-surface-solid);}
/* M5: skrzynka „Ekipy” — jasna pigułka jak „Dodaj wydarzenie”, z czymś do zrobienia -> kolor akcentu. */
.st-key-m1_actions .st-key-m5_inbox button {
  background: var(--krk-surface-solid); color: var(--krk-text); border: 1px solid var(--krk-line-strong);
}
.st-key-m1_actions .st-key-m5_inbox button:hover {filter: none; border-color: var(--krk-primary); color: var(--krk-primary);}
.st-key-m1_actions .st-key-m5_inbox button[kind="primary"] {background: var(--krk-grad); color: #fff; border: none;}
.st-key-m1_actions .st-key-m5_inbox button[kind="primary"]:hover {color: #fff; filter: brightness(1.05);}

/* ============ Pasek kategorii (kółka z liczbą jak na job boardach) ============ */
.st-key-m1_catbar {height: var(--krk-catbar); min-height: var(--krk-catbar); padding: 0 20px 4px; justify-content: center; overflow-x: auto; overflow-y: hidden; scrollbar-width: none;}
.st-key-m1_catbar::-webkit-scrollbar {display: none;}
.st-key-m1_catbar [data-testid="stButtonGroup"] {width: max-content; margin: 0 auto;}
.st-key-m1_catbar [data-testid="stButtonGroup"] > div {flex-wrap: nowrap !important; gap: 4px !important; justify-content: center;}
.st-key-m1_catbar button[data-variant^="pills"] {
  position: relative; flex-direction: column; gap: 5px; height: 78px; min-width: 74px; padding: 10px 4px 2px;
  border: none !important; background: transparent !important; box-shadow: none !important; border-radius: 14px;
  color: var(--krk-text); overflow: visible;
}
.st-key-m1_catbar button[data-variant^="pills"] > div, .st-key-m1_catbar button[data-variant^="pills"] span {
  flex-direction: column; overflow: visible;
}
/* Streamlit trzyma ikonę w opakowaniu 16 px z overflow: hidden — bez tego kółko ma uciętą górę. */
.st-key-m1_catbar button[data-variant^="pills"] span:has(> [data-testid="stIconMaterial"]) {
  width: auto !important; height: auto !important; min-height: 0; line-height: normal;
}
.st-key-m1_catbar button[data-variant^="pills"] [data-testid="stIconMaterial"] {
  width: 42px !important; height: 42px !important; min-height: 42px; line-height: 42px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  font-size: 21px; color: #fff; margin: 0 !important;
  background: linear-gradient(140deg, color-mix(in srgb, var(--cat) 62%, #fff), var(--cat));
  box-shadow: 0 6px 14px -6px color-mix(in srgb, var(--cat) 80%, transparent);
  transition: transform .18s ease, box-shadow .18s ease;
}
.st-key-m1_catbar button[data-variant^="pills"] [data-testid="stMarkdownContainer"] p {
  font-size: 0.72rem; font-weight: 600; letter-spacing: 0.01em; white-space: nowrap; color: var(--krk-muted);
  font-family: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
}
.st-key-m1_catbar button[data-variant^="pills"]:hover [data-testid="stIconMaterial"] {transform: translateY(-2px) scale(1.05);}
.st-key-m1_catbar button[aria-pressed="true"] [data-testid="stIconMaterial"] {
  box-shadow: 0 0 0 3px var(--krk-surface-solid), 0 0 0 5px var(--cat), 0 8px 16px -6px var(--cat);
}
.st-key-m1_catbar button[aria-pressed="true"] [data-testid="stMarkdownContainer"] p {color: var(--krk-text);}
/* Licznik: mała pigułka przy prawym górnym rogu kółka (treść wstawia category_css). */
.st-key-m1_catbar button[data-variant^="pills"]::after {
  position: absolute; z-index: 1; top: 1px; left: calc(50% + 13px);
  height: 18px; min-width: 18px; padding: 0 6px; box-sizing: border-box; border-radius: 999px;
  display: flex; align-items: center; justify-content: center;
  font: 700 10.5px/1 Inter, system-ui, sans-serif; font-variant-numeric: tabular-nums; letter-spacing: 0.01em;
  background: var(--krk-surface-solid); color: var(--krk-text);
  box-shadow: 0 0 0 1.5px color-mix(in srgb, var(--cat) 55%, transparent), 0 2px 6px rgba(15, 23, 42, .18);
  pointer-events: none; transition: background .18s ease, color .18s ease;
}
.st-key-m1_catbar button[aria-pressed="true"]::after {
  background: var(--cat); color: #fff; box-shadow: 0 0 0 2px var(--krk-surface-solid), 0 2px 6px rgba(15, 23, 42, .25);
}

/* ============ Pływające panele ============ */
.st-key-m1_left, .st-key-m1_right, .st-key-m1_sheet {
  position: fixed !important; top: var(--krk-top); bottom: var(--krk-gap); z-index: 20;
  transition: transform .38s cubic-bezier(.22, .9, .25, 1);
}
.st-key-m1_left {left: var(--krk-gap); width: var(--krk-left-w);}
.st-key-m1_right {right: var(--krk-gap); width: var(--krk-right-w);}
/* Czat / profil / formularz: szeroki arkusz nad listą (lista dalej istnieje -> filtry nie giną). */
.st-key-m1_sheet {
  left: var(--krk-gap); width: min(__SHEET_W__px, calc(100vw - var(--krk-right-w) - 4 * var(--krk-gap))); z-index: 21;
  animation: m1-sheet-in .32s cubic-bezier(.22, .9, .25, 1);
}
@keyframes m1-sheet-in {from {opacity: 0; transform: translateX(-24px);} to {opacity: 1; transform: none;}}
.st-key-m1_left > [data-testid="stLayoutWrapper"], .st-key-m1_right > [data-testid="stLayoutWrapper"] {height: 100%;}
.st-key-m1_left_body, .st-key-m1_right_body, .st-key-m1_sheet {
  height: 100%; overflow-y: auto; overflow-x: hidden; scrollbar-width: thin; overscroll-behavior: contain;
  background: var(--krk-surface); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
  border-radius: var(--krk-radius); box-shadow: var(--krk-shadow), 0 0 0 1px var(--krk-line);
  padding: 18px 18px 22px; gap: 0.7rem !important; flex-wrap: nowrap !important;
}
.st-key-m1_left:has(.st-key-m1_left_toggle input:checked) {transform: translateX(calc(-100% - var(--krk-gap)));}
.st-key-m1_right:has(.st-key-m1_right_toggle input:checked) {transform: translateX(calc(100% + var(--krk-gap)));}

/* Uchwyty chowania paneli (checkbox wyglądający jak zakładka). */
.st-key-m1_left_toggle, .st-key-m1_right_toggle {
  position: absolute !important; top: 18px; z-index: 5; width: 34px !important; height: 54px;
}
.st-key-m1_left_toggle {right: -34px;}
.st-key-m1_right_toggle {left: -34px;}
.st-key-m1_left_toggle label, .st-key-m1_right_toggle label {
  width: 34px; height: 54px; margin: 0; padding: 0; cursor: pointer; display: flex; align-items: center;
  justify-content: center; background: var(--krk-surface-solid); color: var(--krk-text);
  box-shadow: var(--krk-shadow-sm), 0 0 0 1px var(--krk-line); transition: color .15s ease;
}
.st-key-m1_left_toggle label {border-radius: 0 12px 12px 0;}
.st-key-m1_right_toggle label {border-radius: 12px 0 0 12px;}
.st-key-m1_left_toggle label:hover, .st-key-m1_right_toggle label:hover {color: var(--krk-primary);}
.st-key-m1_left_toggle label > *, .st-key-m1_right_toggle label > * {display: none !important;}
.st-key-m1_left_toggle label::before, .st-key-m1_right_toggle label::before {
  font-family: "Material Symbols Rounded"; font-size: 22px; line-height: 1; transition: transform .3s ease;
}
.st-key-m1_left_toggle label::before {content: "chevron_left";}
.st-key-m1_right_toggle label::before {content: "chevron_right";}
.st-key-m1_left_toggle:has(input:checked) label::before {transform: rotate(180deg);}
.st-key-m1_right_toggle:has(input:checked) label::before {transform: rotate(180deg);}

/* ============ Lista wydarzeń ============ */
.m1-panel-title {font-size: 1.15rem; font-weight: 750; letter-spacing: -0.02em; color: var(--krk-text); line-height: 1.2;}
.m1-panel-sub {font-size: 0.8rem; color: var(--krk-muted); margin-top: 2px;}
.m1-panel-sub b {color: var(--krk-text); font-weight: 650;}
.st-key-m1_list_head {gap: 4px !important; flex-wrap: nowrap !important;}
.st-key-m1_list_head > [data-testid="stElementContainer"]:first-child {flex: 1 1 auto !important; min-width: 0; width: auto !important;}
.st-key-m1_list_head [data-testid="stSelectbox"] [data-baseweb="select"] > div {
  border-radius: 999px; min-height: 0; height: 34px; font-size: 0.8rem; background: var(--krk-soft);
  border-color: transparent;
}
.m1-count {
  display: inline-block; vertical-align: 3px; margin-left: 4px; padding: 1px 8px; border-radius: 999px;
  font-size: 0.72rem; font-weight: 700; background: var(--krk-primary-soft); color: var(--krk-primary);
  font-family: "JetBrains Mono", ui-monospace, monospace; letter-spacing: 0;
}
.st-key-m1_f_clear button {
  width: 34px; height: 34px; min-height: 0; padding: 0; border-radius: 50%; color: var(--krk-muted);
}
.st-key-m1_f_clear button:hover {color: var(--krk-primary); background: var(--krk-soft);}

[class*="st-key-m1_f_when"] [data-testid="stButtonGroup"] > div {
  flex-wrap: nowrap !important; overflow-x: auto; scrollbar-width: none; gap: 5px !important;
  mask-image: linear-gradient(90deg, #000 88%, transparent); -webkit-mask-image: linear-gradient(90deg, #000 88%, transparent);
  padding-right: 24px;
}
[class*="st-key-m1_f_when"] [data-testid="stButtonGroup"] > div::-webkit-scrollbar {display: none;}
.m1-where {display: flex; align-items: center; gap: 3px;}
.m1-where .material-ico {font-size: 15px;}
[class*="st-key-m1_f_when"] button[data-variant^="pills"] {
  flex: 0 0 auto; border-radius: 999px; height: 32px; min-height: 0; padding: 0 11px; white-space: nowrap;
  background: var(--krk-soft); border: 1px solid transparent; font-size: 0.8rem; font-weight: 500;
}
[class*="st-key-m1_f_when"] button[aria-pressed="true"] {
  background: var(--krk-primary-soft); border-color: var(--krk-primary); color: var(--krk-primary); font-weight: 650;
}
[class*="st-key-m1_f_when"] button[data-variant^="pills"] p {font-size: 0.8rem;}
.st-key-m1_filters_row {gap: 10px !important; flex-wrap: nowrap !important;}
.st-key-m1_filters_row [data-testid="stElementContainer"]:has([data-testid="stMultiSelect"]) {flex: 1 1 auto !important; min-width: 0;}
.st-key-m1_filters_row [data-baseweb="select"] > div {border-radius: 12px; background: var(--krk-soft); border-color: transparent;}
.st-key-m1_filters_row [data-testid="stCheckbox"] label p {font-size: 0.82rem; white-space: nowrap;}
.m1-divider {height: 1px; background: var(--krk-line); margin: 2px -18px;}

/* Karta wydarzenia: cała klikalna (przezroczysty przycisk na wierzchu). */
[class*="st-key-m1_card_"] {position: relative; gap: 0 !important;}
[class*="st-key-m1_card_"] [data-testid="stElementContainer"]:has(button) {
  position: absolute !important; inset: 0; z-index: 2; width: 100% !important; height: 100%;
}
[class*="st-key-m1_card_"] [data-testid="stElementContainer"]:has(button) > div,
[class*="st-key-m1_card_"] [data-testid="stButton"] {width: 100%; height: 100%;}
[class*="st-key-m1_card_"] button {
  width: 100%; height: 100%; opacity: 0; border-radius: 16px; cursor: pointer;
}
.m1-card {
  display: grid; grid-template-columns: 64px 1fr; gap: 6px 14px; padding: 14px; border-radius: 16px;
  background: var(--krk-surface-solid); box-shadow: 0 0 0 1px var(--krk-line);
  transition: box-shadow .18s ease, transform .18s ease;
}
[class*="st-key-m1_card_"]:hover .m1-card {
  box-shadow: 0 0 0 1px var(--krk-line-strong), var(--krk-shadow-sm); transform: translateY(-1px);
}
.m1-card.is-selected {box-shadow: 0 0 0 2px var(--krk-primary), 0 10px 24px -14px rgba(228, 87, 46, .7);}
.m1-thumb {
  --c: #E4572E; width: 64px; height: 64px; border-radius: 14px; position: relative; overflow: hidden;
  background: linear-gradient(140deg, color-mix(in srgb, var(--c) 60%, #fff), var(--c));
  display: flex; align-items: center; justify-content: center; color: #fff; box-shadow: 0 0 0 1px var(--krk-line);
}
.m1-thumb .material-ico {font-size: 28px;}
.m1-thumb-img {position: absolute; inset: 0; background-size: cover; background-position: center;}
.m1-card-main {min-width: 0;}
.m1-card-meta {
  display: flex; align-items: center; gap: 10px; color: var(--krk-muted); font-size: 0.74rem; min-width: 0;
  font-family: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
}
.m1-card-meta span {display: inline-flex; align-items: center; gap: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0;}
.m1-card-meta .material-ico {font-size: 15px;}
.m1-card-title {
  font-size: 1rem; font-weight: 650; letter-spacing: -0.01em; line-height: 1.3; color: var(--krk-text);
  margin: 3px 0 2px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.m1-badge {
  display: inline-block; vertical-align: 2px; margin-left: 6px; padding: 1px 7px; border-radius: 6px;
  font-size: 0.66rem; font-weight: 650; background: var(--krk-primary-soft); color: var(--krk-primary);
  font-family: "JetBrains Mono", ui-monospace, monospace;
}
.m1-price {font-size: 0.98rem; font-weight: 700; color: var(--krk-price); letter-spacing: -0.01em;}
.m1-price small {font-size: 0.72rem; font-weight: 500; color: var(--krk-muted); margin-left: 3px;}
.m1-tags {grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px;}
.m1-tag {
  padding: 3px 9px; border-radius: 7px; font-size: 0.72rem; background: var(--krk-soft); color: var(--krk-text);
  box-shadow: 0 0 0 1px var(--krk-line); font-family: "JetBrains Mono", ui-monospace, monospace;
}
.m1-card-foot {
  grid-column: 1 / -1; display: flex; align-items: center; gap: 8px; margin-top: 6px; padding-top: 10px;
  border-top: 1px solid var(--krk-line); font-size: 0.8rem; font-weight: 600; color: var(--krk-text);
}
.m1-card-foot .dot {width: 3px; height: 3px; border-radius: 50%; background: var(--krk-faint);}
.m1-card-foot .muted {color: var(--krk-muted); font-weight: 500;}
.m1-card-foot .right {margin-left: auto; color: var(--krk-muted); font-weight: 500; display: inline-flex; align-items: center; gap: 3px;}
.m1-card-foot .material-ico {font-size: 16px;}
.st-key-m1_more button {border-radius: 999px; border: 1px dashed var(--krk-line-strong); background: transparent;}
.m1-empty {text-align: center; padding: 28px 10px 10px; color: var(--krk-muted);}
.m1-empty .material-ico {font-size: 44px; color: var(--krk-faint);}
.m1-empty b {display: block; color: var(--krk-text); font-size: 1rem; margin: 6px 0 2px;}

/* ============ Panel szczegółów ============ */
.st-key-m1_right_body {padding-top: 14px;}
.st-key-m1_detail_head {gap: 6px !important;}
.st-key-m1_detail_head button {
  width: 36px; height: 36px; min-height: 0; padding: 0; border-radius: 50%; border: none;
  background: var(--krk-soft); color: var(--krk-text);
}
.st-key-m1_detail_head button:hover {background: var(--krk-soft-2); color: var(--krk-primary);}
.m1-hero {
  --c: #E4572E; position: relative; height: 172px; border-radius: 16px; overflow: hidden; margin-top: 2px;
  background: linear-gradient(140deg, color-mix(in srgb, var(--c) 55%, #fff), var(--c));
  display: flex; align-items: center; justify-content: center; color: rgba(255, 255, 255, .9);
}
.m1-hero .material-ico {font-size: 64px;}
.m1-hero-img {position: absolute; inset: 0; background-size: cover; background-position: center;}
.m1-hero::after {content: ""; position: absolute; inset: 0; background: linear-gradient(180deg, transparent 45%, rgba(0, 0, 0, .55));}
.m1-hero-badge {
  position: absolute; left: 12px; bottom: 12px; z-index: 1; display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 10px 4px 7px; border-radius: 999px; background: rgba(255, 255, 255, .92); color: #0F172A;
  font-size: 0.75rem; font-weight: 650;
}
.m1-hero-badge .material-ico {font-size: 16px; color: var(--c);}
.m1-hero-src {
  position: absolute; right: 12px; bottom: 12px; z-index: 1; font-size: 0.68rem; color: rgba(255, 255, 255, .85);
  font-family: "JetBrains Mono", ui-monospace, monospace;
}
.m1-detail-title {font-size: 1.32rem; font-weight: 750; letter-spacing: -0.025em; line-height: 1.25; color: var(--krk-text); margin-top: 4px;}
.m1-facts {display: grid; gap: 9px; margin: 2px 0 4px;}
.m1-fact {display: flex; align-items: flex-start; gap: 10px; font-size: 0.88rem; color: var(--krk-text); line-height: 1.35;}
.m1-fact .ico {
  flex: 0 0 30px; height: 30px; border-radius: 9px; background: var(--krk-soft); display: flex;
  align-items: center; justify-content: center; color: var(--krk-muted);
}
.m1-fact .ico .material-ico {font-size: 18px;}
.m1-fact small {display: block; color: var(--krk-muted); font-size: 0.76rem;}
.m1-fact .price {color: var(--krk-price); font-weight: 700;}
.m1-desc {font-size: 0.85rem; color: var(--krk-muted); line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden;}
.m1-section {
  display: flex; align-items: center; gap: 8px; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--krk-muted); margin-top: 6px;
}
.m1-section::after {content: ""; flex: 1; height: 1px; background: var(--krk-line);}
/* M5: wejście do czatu grupy (moja ekipa / nowa ekipa / zaproszenie) — główna akcja panelu. */
[class*="st-key-m5_grp_open_"] button, [class*="st-key-m5_grp_new_"] button, [class*="st-key-m5_grp_view_"] button {
  border-radius: 12px; height: 44px; font-weight: 650; border: none; color: #fff; background: var(--krk-grad);
  box-shadow: 0 10px 22px -12px rgba(228, 87, 46, .9);
}
[class*="st-key-m5_grp_open_"] button:hover, [class*="st-key-m5_grp_new_"] button:hover,
[class*="st-key-m5_grp_view_"] button:hover {color: #fff; filter: brightness(1.05);}
[class*="st-key-m5_grp_invite_"] {border-color: var(--krk-primary) !important; background: var(--krk-primary-soft);}
.st-key-m1_right_body [data-testid="stLinkButton"] a {border-radius: 12px; height: 44px;}
.st-key-m1_right_body h4 {font-size: 1rem; font-weight: 700; letter-spacing: -0.01em;}

/* Karty modułów M3/M4 w panelu (kontenery z ramką) w tym samym stylu co karty listy. */
.st-key-m1_recs > [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"],
.st-key-m1_matches > [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"] {
  border: none; border-radius: 16px; background: var(--krk-surface-solid); padding: 14px;
  box-shadow: 0 0 0 1px var(--krk-line); transition: box-shadow .18s ease, transform .18s ease;
}
.st-key-m1_recs > [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]:hover,
.st-key-m1_matches > [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]:hover {
  box-shadow: 0 0 0 1px var(--krk-line-strong), var(--krk-shadow-sm); transform: translateY(-1px);
}
.st-key-m1_recs code {
  background: var(--krk-soft); color: var(--krk-text); border-radius: 7px; padding: 2px 8px; font-size: 0.72rem;
  box-shadow: 0 0 0 1px var(--krk-line);
}

/* ============ Menu (popover) ============ */
[data-testid="stPopoverBody"]:has(.st-key-m1_menu_body) {min-width: 300px; padding: 0.4rem; border-radius: 16px;}
.st-key-m1_menu_body [data-testid="stBaseButton-tertiary"],
.st-key-m1_menu_body .st-key-m3_user_switch_new button {
  width: 100%; justify-content: flex-start; padding: 0.5rem 0.6rem; border-radius: 0.6rem;
  border: none; background: transparent; box-shadow: none; min-height: 0;
}
.st-key-m1_menu_body button > div {justify-content: flex-start;}
.st-key-m1_menu_body [data-testid="stBaseButton-tertiary"]:hover,
.st-key-m1_menu_body .st-key-m3_user_switch_new button:hover {background: rgba(128, 128, 128, 0.12);}
.st-key-m1_menu_body [data-testid="stWidgetLabel"] p {
  font-size: 0.7rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.55;
}
.st-key-m1_menu_body .st-key-m3_user_switch,
.st-key-m1_menu_body [data-testid="stCaptionContainer"] {padding: 0.25rem 0.6rem 0;}
.m1-menu-user {
  display: flex; align-items: center; gap: 10px; padding: 0.4rem 0.6rem 0.6rem; margin-bottom: 0.35rem;
  border-bottom: 1px solid rgba(128, 128, 128, 0.2);
}
.m1-menu-user .m1-hello {font-size: 0.95rem; font-weight: 650;}
.m1-sep {height: 1px; background: rgba(128, 128, 128, 0.2); margin: 0.35rem 0;}
.st-key-m1_menu_reset [data-testid="stBaseButton-tertiary"] {color: #D9431A;}

/* M5: skrzynka „Ekipy” i lista „Idą / Interesuje ich” — pozycje jak w menu. */
[data-testid="stPopoverBody"]:has([class*="st-key-m5_pop_"]) {min-width: 320px; max-width: 400px; padding: 0.4rem; border-radius: 16px;}
[class*="st-key-m5_pop_"] [data-testid="stBaseButton-tertiary"] {
  width: 100%; justify-content: flex-start; padding: 0.45rem 0.6rem; border-radius: 0.6rem; min-height: 0; text-align: left;
}
[class*="st-key-m5_pop_"] button > div {justify-content: flex-start;}
[class*="st-key-m5_pop_"] [data-testid="stBaseButton-tertiary"]:hover {background: rgba(128, 128, 128, 0.12);}
[class*="st-key-m5_pop_"] [data-testid="stCaptionContainer"] {padding: 0.25rem 0.6rem;}
.m5-pop-head {
  font-size: 0.7rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.55;
  padding: 0.55rem 0.6rem 0.15rem;
}

/* Popover lokalizacji. */
[data-testid="stPopoverBody"]:has(.st-key-m1_loc_body) {width: 380px; padding: 0.9rem 1rem; border-radius: 18px;}
.st-key-m1_loc_body [data-testid="stWidgetLabel"] p {
  font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.6;
}
.st-key-m1_loc_body button[data-variant^="pills"] {border-radius: 999px; font-size: 0.8rem;}
.m1-loc-hint {font-size: 0.78rem; color: var(--krk-muted); line-height: 1.4;}

/* Tryb wskazywania punktu na mapie. */
.m1-pick-banner {
  position: fixed; left: 50%; top: calc(var(--krk-top) + 4px); transform: translateX(-50%); z-index: 25;
  display: flex; align-items: center; gap: 8px; padding: 9px 16px; border-radius: 999px;
  background: var(--krk-text); color: var(--krk-surface-solid); font-size: 0.85rem; font-weight: 600;
  box-shadow: var(--krk-shadow); pointer-events: none; animation: m1-drop .3s ease;
}
@keyframes m1-drop {from {opacity: 0; transform: translate(-50%, -8px);} to {opacity: 1; transform: translate(-50%, 0);}}
.st-key-m1_pick_cancel {
  position: fixed !important; left: 50%; top: calc(var(--krk-top) + 50px); transform: translateX(-50%);
  z-index: 25; width: auto !important;
}
.st-key-m1_pick_cancel button {
  border-radius: 999px; height: 34px; min-height: 0; padding: 0 14px; background: var(--krk-surface-solid);
  border: 1px solid var(--krk-line-strong); box-shadow: var(--krk-shadow-sm); font-size: 0.82rem;
}

/* ============ Wąskie ekrany ============ */
@media (max-width: 1180px) {
  .m1-brand-tag, .m1-header > div:last-child {display: none;}
  .st-key-m1_add_event_top button p {display: none;}
}
@media (max-width: 860px) {
  :root {--krk-gap: 10px; --krk-topbar: 60px; --krk-catbar: 80px;}
  .st-key-m1_topbar_row {padding: 0 10px; gap: 8px !important;}
  .m1-brand > div {display: none;}
  [data-testid="stLayoutWrapper"]:has(> .st-key-m1_search) {min-width: 0; flex: 1 1 auto; margin: 0;}
  .st-key-m1_search {height: 44px;}
  .st-key-m1_search [data-testid="stPopover"] button {padding: 0 8px;}
  .st-key-m1_search [data-testid="stPopover"] button [data-testid="stMarkdownContainer"],
  .st-key-m1_actions [data-testid="stPopover"] button [data-testid="stMarkdownContainer"] {display: none;}
  .st-key-m1_search_go, .st-key-m1_add_event_top,
  .st-key-m1_actions [data-testid="stElementContainer"]:has(.m1-header) {display: none !important;}
  .st-key-m1_actions [data-testid="stPopover"] button {padding: 0 12px;}
  .st-key-m1_catbar {padding: 0 6px 4px;}
  .st-key-m1_catbar [data-testid="stButtonGroup"] {margin: 0;}
  /* Lista = dolny arkusz, szczegóły = pełny ekran tylko po wyborze wydarzenia. */
  .st-key-m1_left {top: 52vh; width: auto; right: var(--krk-gap);}
  .st-key-m1_right {width: auto; left: var(--krk-gap); z-index: 22;}
  .st-key-m1_right:not(:has(.st-key-m1_detail_head)) {transform: translateX(calc(100% + 2 * var(--krk-gap)));}
  .st-key-m1_right:not(:has(.st-key-m1_detail_head)) .st-key-m1_right_toggle {display: none;}
  .st-key-m1_sheet {width: auto; right: var(--krk-gap); z-index: 23;}
}
</style>
"""


def global_css(dark: bool) -> str:
    """Pełny arkusz stylów aplikacji dla danego motywu."""
    return (
        _CSS.replace("__TOKENS__", _TOKENS[dark])
        .replace("__TOPBAR__", str(TOPBAR_H))
        .replace("__CATBAR__", str(CATBAR_H))
        .replace("__GAP__", str(GAP))
        .replace("__LEFT_W__", LEFT_W)
        .replace("__RIGHT_W__", RIGHT_W)
        .replace("__SHEET_W__", str(SHEET_W))
    )


def category_css(categories: Iterable[Category], counts: dict[Category, int]) -> str:
    """Kolor kółka i licznik nad nim dla każdej kategorii (kolejność = kolejność przycisków pills)."""
    rules = []
    for i, category in enumerate(categories, start=1):
        sel = f".st-key-m1_catbar button[data-variant^='pills']:nth-of-type({i})"
        count = counts.get(category, 0)
        rules.append(f"{sel} {{--cat: {CATEGORY_COLORS[category]};}}")
        rules.append(f'{sel}::after {{content: "{count}";}}')
        if not count:
            rules.append(f"{sel} {{opacity: 0.42;}}")
    return "<style>" + "\n".join(rules) + "</style>"


def state_css(*, selected_card: str | None) -> str:
    """Style zależne od stanu: wyróżniona karta na liście (wybrany event)."""
    rules = []
    if selected_card:
        rules.append(
            f".st-key-m1_card_{selected_card} .m1-card, .st-key-m1_card_{selected_card}:hover .m1-card "
            f"{{box-shadow: 0 0 0 2px var(--krk-primary), 0 10px 24px -14px rgba(228, 87, 46, .7);}}"
        )
    return "<style>" + "\n".join(rules) + "</style>" if rules else ""
