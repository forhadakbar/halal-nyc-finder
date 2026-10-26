"""Halal NYC Finder — Streamlit app.

Run:  streamlit run app.py
"""
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from urllib.parse import urlencode

import pandas as pd
import streamlit as st

from agent import Concierge
from data import DATA_BUILD, cache_mtime, load
from halal import TIER_BADGE, TIER_COLOR, TIER_NOTE, add_address, add_match_reason, grade_label

st.set_page_config(page_title="Halal NYC Finder", page_icon="🍽️", layout="wide")

# --- Theme: dark by default, switchable with the top button ------------
# .streamlit/config.toml sets Streamlit's native base theme to dark.
# On top of that, the app injects an explicit skin for the chosen mode
# so the 🌙/☀️ button at the top restyles the whole page (background,
# sidebar, text, inputs, cards) immediately, and the choice is carried
# in the URL (?theme=) exactly like the filters, so it survives the
# ?view= tab switches that start a fresh session.
_qp_theme_vals = list(st.query_params.get_all("theme"))
if "theme" not in st.session_state:
    st.session_state.theme = (
        _qp_theme_vals[0]
        if _qp_theme_vals and _qp_theme_vals[0] in ("dark", "light")
        else "dark"
    )


def _toggle_theme() -> None:
    st.session_state.theme = (
        "light" if st.session_state.get("theme", "dark") == "dark" else "dark"
    )


def _skin_css(mode: str) -> str:
    if mode == "dark":
        bg, sec, txt, inp, border = "#0e1117", "#262730", "#fafafa", "#262730", "rgba(250,250,250,0.18)"
    else:
        bg, sec, txt, inp, border = "#ffffff", "#f0f2f6", "#111827", "#ffffff", "rgba(17,24,39,0.22)"
    return f"""
<style>
[data-testid="stAppViewContainer"] {{ background-color:{bg}; color:{txt}; }}
[data-testid="stSidebar"] {{ background-color:{sec}; color:{txt}; }}
[data-testid="stHeader"] {{ background-color:transparent; }}
[data-testid="stAppViewContainer"] h1, [data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3, [data-testid="stAppViewContainer"] h4,
[data-testid="stAppViewContainer"] p, [data-testid="stAppViewContainer"] span,
[data-testid="stAppViewContainer"] label, [data-testid="stAppViewContainer"] li,
[data-testid="stSidebar"] p, [data-testid="stSidebar"] span,
[data-testid="stSidebar"] label, [data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{ color:{txt}; }}
[data-testid="stAppViewContainer"] .placard {{ color:#111827; }}
[data-testid="stAppViewContainer"] .placard-head {{ color:#ffffff; }}
.stButton > button {{ color:{txt}; border-color:{border}; }}
[data-testid="stAppViewContainer"] div[data-baseweb="select"] > div {{
  background-color:{inp}; color:{txt}; border-color:{border}; }}
[data-testid="stAppViewContainer"] div[data-baseweb="input"] {{
  background-color:{inp}; border-color:{border}; }}
[data-testid="stAppViewContainer"] input,
[data-testid="stAppViewContainer"] textarea {{ color:{txt}; }}
[data-testid="stExpander"] {{ border-color:{border}; }}
div[data-baseweb="popover"] ul, ul[role="listbox"] {{ background-color:{sec}; }}
ul[role="listbox"] li {{ color:{txt}; }}
[data-testid="stChatMessage"] {{ background-color:{sec}; }}
[data-testid="stChatInput"] textarea {{ background-color:{inp}; color:{txt}; }}
</style>"""


st.markdown(_skin_css(st.session_state.theme), unsafe_allow_html=True)

# Bottom-tab views, switched through the ?view= query param so tabs are
# real links (bookmarkable, no JS needed).
VIEWS = {"map": "🗺️ Map", "list": "📋 List", "ask": "💬 Ask"}

GRADE_STYLE = {
    "A": "background:#1f9d55;color:#fff;",
    "B": "background:#cf8a0a;color:#fff;",
    "C": "background:#d9534f;color:#fff;",
}


def grade_pill(grade: str, detail=None) -> str:
    """Colored grade badge for the list cards (Zabihah-style).

    When there is no A/B/C letter grade, say why: the city marks new or
    not-yet-graded spots N (not yet graded) and Z/P (grade pending).
    """
    if grade in GRADE_STYLE:
        return (
            f'<span style="{GRADE_STYLE[grade]}padding:3px 12px;'
            'border-radius:999px;font-weight:800;font-size:14px;'
            f'white-space:nowrap;">Grade {grade}</span>'
        )
    label = {"Z": "Grade pending", "P": "Grade pending", "N": "Not yet graded"}.get(
        str(detail).strip().upper(), "Not graded"
    )
    return (
        '<span style="background:#6c757d;color:#fff;padding:3px 12px;'
        f'border-radius:999px;font-size:13px;white-space:nowrap;">{label}</span>'
    )


def _fmt_phone(raw):
    """'7185232600' -> ('(718) 523-2600', 'tel:+17185232600')."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}", f"tel:+1{digits}"
    return (str(raw) if pd.notna(raw) and str(raw) else ""), (f"tel:{digits}" if digits else "")


def _score_band(score: int) -> str:
    if score <= 13:
        return "A-range score — cleanest inspections"
    if score <= 27:
        return "B-range score"
    return "C-range score — most violations"


CARD_CSS = """
<style>
.rlist { display:grid; grid-template-columns:1fr; gap:14px; margin-bottom:14px; }
@media (min-width:1000px) { .rlist { grid-template-columns:1fr 1fr; } }
.rcard { border:1px solid rgba(128,128,128,0.28); border-radius:16px;
  overflow:hidden; background:rgba(128,128,128,0.05); display:flex; }
.rcard-main { flex:1; min-width:0; }
.placard { flex:none; width:84px; margin:12px 0 12px 12px; align-self:stretch;
  display:flex; flex-direction:column; background:#ffffff; color:#111827;
  border:2px solid #111827; border-radius:10px; overflow:hidden; text-align:center; }
.placard-head { background:#111827; color:#ffffff; font-size:9px; font-weight:800;
  letter-spacing:0.1em; padding:5px 2px; white-space:nowrap; }
.placard-letter { flex:1; display:flex; align-items:center; justify-content:center;
  font-size:52px; font-weight:900; line-height:1; padding:6px 0 2px 0; }
.placard-foot { font-size:8.5px; font-weight:800; letter-spacing:0.06em;
  opacity:0.65; padding:0 3px 6px 3px; }
@media (max-width:560px) {
  .placard { width:70px; }
  .placard-letter { font-size:42px; }
}
.rcard-top { display:flex; justify-content:flex-start; align-items:center;
  gap:8px; margin-bottom:8px; }
.rcard-tier { background:rgba(128,128,128,0.12); color:inherit;
  border:1px solid rgba(128,128,128,0.25); padding:4px 10px;
  border-radius:999px; font-size:12px; font-weight:700; white-space:nowrap; }
.rcard-body { padding:12px 14px 14px 14px; }
.rcard-name { font-size:18px; font-weight:800; line-height:1.25; margin-bottom:2px; }
.rcard-meta { font-size:13px; opacity:0.78; line-height:1.5; }
.rcard-score { display:flex; align-items:center; gap:8px; margin-top:9px; font-size:13px; }
.rcard-bar { flex:1; height:6px; border-radius:999px; background:rgba(128,128,128,0.25);
  overflow:hidden; }
.rcard-barfill { height:100%; background:#64748b; border-radius:999px; }
.rcard-actions { display:flex; gap:8px; margin-top:12px; }
.rbtn { flex:1; text-align:center; padding:9px 8px; border-radius:10px; font-weight:700;
  font-size:14px; text-decoration:none; border:1px solid rgba(128,128,128,0.45); color:inherit; }
.rbtn-primary { background:#ff4b2b; border-color:transparent; color:#fff !important; }
.gdetails { margin-top:10px; border-top:1px solid rgba(128,128,128,0.25); padding-top:8px; }
.gdetails summary { cursor:pointer; font-weight:700; font-size:14px; }
.gdetails-body { font-size:13px; line-height:1.55; margin-top:8px; }
.gdetails-body ul { margin:6px 0 6px 16px; padding:0; }
.gdetails-body li { margin-bottom:4px; }
.gsec { font-weight:800; margin-top:11px; }
.bandwrap { position:relative; margin-top:4px; padding-top:13px; }
.bandmarker { position:absolute; top:0; transform:translateX(-50%); font-size:10px; }
.bandbar { display:flex; height:16px; border-radius:6px; overflow:hidden; }
.bandseg { color:#fff; font-size:10px; font-weight:800; display:flex;
  align-items:center; justify-content:center; }
.bandcap { font-size:12px; opacity:0.75; margin-top:4px; }
.histline { margin:2px 0; }
</style>
"""


PLACARD_COLORS = {"A": "#1f9d55", "B": "#cf8a0a", "C": "#d9534f"}


def _placard(r) -> str:
    """Mini version of the official NYC grade sign posted in restaurant
    windows: dark header, one huge letter, small caption. Ungraded spots
    get a grey dash with the reason as the caption."""
    grade = r.get("grade")
    if grade in PLACARD_COLORS:
        letter, color, foot = grade, PLACARD_COLORS[grade], "INSPECTION GRADE"
    else:
        letter, color = "–", "#6c757d"
        foot = (
            "GRADE PENDING"
            if str(r.get("grade_detail")).strip().upper() in ("Z", "P")
            else "NOT YET GRADED"
        )
    return (
        '<div class="placard"><div class="placard-head">NYC HEALTH</div>'
        f'<div class="placard-letter" style="color:{color}">{letter}</div>'
        f'<div class="placard-foot">{foot}</div></div>'
    )


def _json_list(raw) -> list:
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []


def _fmt_iso_date(s) -> str:
    try:
        return pd.to_datetime(s).strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return str(s)


def _grade_details(r) -> str:
    """The clickable 'Grade details' expander inside each card: what the
    grade/score mean, the violations behind them, and past inspections.
    Pure HTML <details> — expands in place, no rerun, no extra load."""
    grade = r.get("grade")
    score = r.get("score")
    has_score = pd.notna(score)
    s_int = int(score) if has_score else None

    grade_date = r.get("grade_date")
    gd_txt = ""
    if pd.notna(grade_date):
        try:
            gd_txt = f" · Graded {grade_date:%b %d, %Y}"
        except (TypeError, ValueError):
            gd_txt = ""
    itype = r.get("inspection_type")
    type_txt = (
        f'<div class="rcard-meta">Inspection type: {html.escape(str(itype))}</div>'
        if pd.notna(itype) and str(itype).strip()
        else ""
    )
    if grade in ("A", "B", "C"):
        head = f"<b>Grade {grade}</b>" + (f" · Score {s_int}" if has_score else "") + gd_txt
    elif has_score:
        head = f"<b>Not graded yet</b> · Score {s_int} at the latest inspection" + gd_txt
    else:
        head = "<b>No grade or score issued yet</b>"

    band = ""
    if has_score:
        pct = min(s_int, 42) / 42 * 100
        band = (
            '<div class="bandwrap">'
            f'<div class="bandmarker" style="left:{pct:.0f}%">▼</div>'
            '<div class="bandbar">'
            '<span class="bandseg" style="background:#1f9d55;flex:14">A</span>'
            '<span class="bandseg" style="background:#cf8a0a;flex:14">B</span>'
            '<span class="bandseg" style="background:#d9534f;flex:15">C</span>'
            "</div>"
            '<div class="bandcap">▼ this score · 0–13 pts = A · 14–27 = B · 28+ = C '
            "— fewer points means a cleaner inspection</div></div>"
        )

    violations = _json_list(r.get("violations_json"))
    if violations:
        n_crit = sum(1 for v in violations if v.get("critical"))
        items = ""
        for v in violations[:10]:
            mark = "🔴" if v.get("critical") else "•"
            crit_txt = ' <b style="color:#d9534f">Critical</b>' if v.get("critical") else ""
            code_txt = (
                f' <span style="opacity:0.6">[{html.escape(str(v.get("code")))}]</span>'
                if v.get("code")
                else ""
            )
            items += f"<li>{mark} {html.escape(str(v.get('desc', '')))}{crit_txt}{code_txt}</li>"
        if len(violations) > 10:
            items += f"<li>…and {len(violations) - 10} more in the city record</li>"
        viol_html = (
            f'<div class="gsec">Violations at this inspection — '
            f"{len(violations)} cited · {n_crit} critical</div><ul>{items}</ul>"
        )
    else:
        viol_html = (
            '<div class="gsec">Violations at this inspection</div>'
            "<div>None recorded — a clean inspection. 🎉</div>"
        )

    history = _json_list(r.get("history_json"))
    hist_html = ""
    if history:
        lines = ""
        for h in history[:6]:
            g = h.get("grade")
            if g in ("A", "B", "C"):
                g_txt = f"Grade {g}"
            elif str(h.get("detail")).upper() in ("Z", "P"):
                g_txt = "Grade pending"
            else:
                g_txt = "Not graded"
            sc = h.get("score")
            sc_txt = f" · Score {int(sc)}" if isinstance(sc, (int, float)) else ""
            lines += (
                f'<div class="histline">{html.escape(_fmt_iso_date(h.get("date")))}'
                f" — {g_txt}{sc_txt}</div>"
            )
        hist_html = f'<div class="gsec">Inspection history</div>{lines}'

    return (
        '<details class="gdetails"><summary>📋 Grade details</summary>'
        f'<div class="gdetails-body"><div>{head}</div>{type_txt}{band}'
        f"{viol_html}{hist_html}</div></details>"
    )


def _restaurant_card(r) -> str:
    """One List-view card: badges, inspection info, and Directions / Call
    actions. No images at all — per-restaurant map thumbnails made the
    list slow and never looked like real photos, so the card is kept
    light and fast; a visual treatment is a separate design choice."""
    name_raw = str(r["dba"])
    name = html.escape(name_raw.title())
    cuisine = html.escape(str(r["cuisine_description"]))
    boro = html.escape(str(r["boro"]))
    address_raw = str(r["address"])
    address = html.escape(address_raw)
    tier_badge = html.escape(TIER_BADGE.get(r["halal_tier"], str(r["halal_tier"])))

    top_row = (
        '<div class="rcard-top">'
        f'<span class="rcard-tier">{tier_badge}</span>'
        "</div>"
    )

    zip_raw = r.get("zipcode")
    zip_txt = ""
    if pd.notna(zip_raw) and str(zip_raw).strip().lower() not in ("nan", "none", ""):
        zip_txt = f" · {html.escape(str(zip_raw).strip())}"
    meta1 = f"{cuisine} · {boro}{zip_txt}"

    insp = r.get("inspection_date")
    date_txt = ""
    if pd.notna(insp):
        try:
            date_txt = f" · Inspected {insp:%b %d, %Y}"
        except (TypeError, ValueError):
            date_txt = ""
    reason = {
        "name": "✔ 'Halal' in the name",
        "cuisine": "✔ 'Halal' in the cuisine listing",
        "name + cuisine": "✔ 'Halal' in name & cuisine",
    }.get(str(r.get("halal_match", "")), "")
    meta2 = f"📍 {address}"
    meta3 = " · ".join(x for x in [reason, date_txt.lstrip(" ·")] if x)

    score = r.get("score")
    if pd.notna(score):
        s = int(score)
        bar_w = min(s, 42) / 42 * 100
        score_html = (
            f'<div class="rcard-score"><span>Score <b>{s}</b></span>'
            f'<span class="rcard-bar"><span class="rcard-barfill" '
            f'style="display:block;width:{bar_w:.0f}%"></span></span>'
            f'<span style="opacity:0.75">{_score_band(s)}</span></div>'
        )
    else:
        score_html = '<div class="rcard-meta" style="margin-top:9px">Inspection score not available yet</div>'

    maps_url = html.escape(
        "https://www.google.com/maps/search/?"
        + urlencode({"api": "1", "query": f"{name_raw} {address_raw}"}),
        quote=True,
    )
    phone_disp, tel_href = _fmt_phone(r.get("phone"))
    call_btn = (
        f'<a class="rbtn" href="{html.escape(tel_href, quote=True)}">📞 {html.escape(phone_disp)}</a>'
        if tel_href
        else ""
    )
    actions = (
        '<div class="rcard-actions">'
        f'<a class="rbtn rbtn-primary" href="{maps_url}" target="_blank" rel="noopener">🧭 Directions</a>'
        f"{call_btn}</div>"
    )

    return (
        f'<div class="rcard">{_placard(r)}<div class="rcard-main"><div class="rcard-body">'
        + top_row
        + f'<div class="rcard-name">{name}</div>'
        f'<div class="rcard-meta">{meta1}</div>'
        f'<div class="rcard-meta">{meta2}</div>'
        + (f'<div class="rcard-meta">{html.escape(meta3)}</div>' if meta3 else "")
        + score_html
        + _grade_details(r)
        + actions
        + "</div></div></div>"
    )


@st.cache_data(show_spinner="Loading NYC restaurant data…")
def get_data(schema_version: str) -> pd.DataFrame:
    # schema_version (= data.py's DATA_BUILD) is part of the cache key on
    # purpose: Streamlit Cloud's server process is long-lived and its
    # cache survives code pushes when a function's own code is unchanged,
    # so a pipeline change that only touches data.py would otherwise keep
    # serving the old dataframe forever (bit us 2026-10-22: the live app
    # ran the new UI against pre-violations data). Bumping DATA_BUILD in
    # data.py now guarantees a fresh load.
    df = load()
    df = add_match_reason(df)
    df = add_address(df)
    return df


df = get_data(DATA_BUILD)
concierge = Concierge(df)

n_confirmed = int((df["halal_tier"] == "confirmed").sum())
n_likely = int((df["halal_tier"] == "likely").sum())

st.title("🍽️ Halal NYC Finder")
st.caption(
    f"{n_confirmed} confirmed halal · {n_likely} likely halal spots across NYC · "
    "NYC Open Data (DOHMH inspections) · hygiene grades included"
)
st.caption(TIER_NOTE)

# --- Top actions: theme toggle + data refresh ---------------------------
# The sidebar is collapsed/hidden on phones, so both actions live at the
# top of the dashboard where they're always reachable.
_url_theme_vals = list(st.query_params.get_all("theme"))
if not _url_theme_vals or _url_theme_vals[0] != st.session_state.theme:
    try:
        st.query_params["theme"] = st.session_state.theme
    except Exception:
        pass
_act_theme, _act_refresh = st.columns(2)
with _act_theme:
    st.button(
        "☀️ Light mode" if st.session_state.theme == "dark" else "🌙 Dark mode",
        on_click=_toggle_theme,
        use_container_width=True,
    )
with _act_refresh:
    if st.button("🔄 Refresh data", use_container_width=True):
        with st.spinner("Fetching the latest from NYC Open Data…"):
            load(refresh=True)
            st.cache_data.clear()
        st.rerun()

# --- Grade metrics (whole dataset, not the filtered view) ---
_total = len(df)
_n_a = int((df["grade"] == "A").sum())
_n_b = int((df["grade"] == "B").sum())
_n_c = int((df["grade"] == "C").sum())
_n_not_graded = int(df["grade"].isna().sum())

def _pct(n: int) -> str:
    return f"{(n / _total * 100):.1f}% of all" if _total else ""

# KPI cards as a custom CSS grid — st.columns()/st.metric stack into one
# tall vertical column on phones. Dashboard best practice for KPIs:
# one number per card, label small above, % context below, and a grid
# that wraps to fewer columns per row instead of collapsing to one.
#
# Design (2026-10-26, "too generic" pass): each card gets an identity
# instead of five identical grey boxes — a ghost grade letter watermark
# on the grade cards (echoing the placard seals on the list cards), a
# share-of-total bar under the number, and a hero treatment for Total
# (brand-orange accent, the only color pop in the strip).
#
# Color discipline: green/amber already mean halal tier on this page
# (map pins + badges: green = confirmed, amber = likely), so the KPI
# strip uses NO grade traffic-light colors and no colored dots — the
# bars and accents are slate + brand orange only, and the grade letter
# in the label carries the meaning. A color must mean one thing per
# screen.
def _share(n: int) -> float:
    return (n / _total * 100) if _total else 0.0


_kpis = [
    ("Total spots", _total, "across NYC", "", True),
    ("Grade A", _n_a, _pct(_n_a), "A", False),
    ("Grade B", _n_b, _pct(_n_b), "B", False),
    ("Grade C", _n_c, _pct(_n_c), "C", False),
    ("Not yet graded", _n_not_graded, _pct(_n_not_graded), "–", False),
]
_cards = "".join(
    f'<div class="kpi-card{" kpi-hero" if hero else ""}">'
    f'<div class="kpi-ghost">{ghost}</div>'
    f'<div class="kpi-label">{label}</div>'
    f'<div class="kpi-value">{value:,}</div>'
    f'<div class="kpi-bar"><span style="width:{_share(value) if not hero else 100:.1f}%"></span></div>'
    f'<div class="kpi-sub">{sub}</div></div>'
    for label, value, sub, ghost, hero in _kpis
)
st.markdown(
    """
<style>
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 10px;
    margin: 4px 0 14px 0;
}
.kpi-card {
    position: relative;
    overflow: hidden;
    border: 1px solid rgba(128, 128, 128, 0.28);
    border-radius: 16px;
    padding: 12px 14px 10px 14px;
    background: rgba(128, 128, 128, 0.07);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
    min-width: 0;
}
.kpi-card.kpi-hero {
    border-color: rgba(255, 75, 43, 0.55);
    background: linear-gradient(160deg, rgba(255, 75, 43, 0.16), rgba(128, 128, 128, 0.07) 65%);
}
.kpi-ghost {
    position: absolute;
    right: 2px;
    top: -18px;
    font-size: 76px;
    font-weight: 900;
    line-height: 1;
    opacity: 0.10;
    pointer-events: none;
}
.kpi-hero .kpi-ghost { display: none; }
.kpi-label {
    position: relative;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    opacity: 0.75;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.kpi-value {
    position: relative;
    font-size: clamp(22px, 5vw, 30px);
    font-weight: 800;
    line-height: 1.15;
}
.kpi-bar {
    position: relative;
    height: 4px;
    border-radius: 999px;
    background: rgba(128, 128, 128, 0.25);
    margin: 6px 0 5px 0;
    overflow: hidden;
}
.kpi-bar span {
    display: block;
    height: 100%;
    border-radius: 999px;
    background: #64748b;
}
.kpi-hero .kpi-bar span { background: #ff4b2b; }
.kpi-sub { position: relative; font-size: 12px; opacity: 0.7; white-space: nowrap; }
@media (max-width: 900px) {
    .kpi-grid { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 560px) {
    .kpi-grid { grid-template-columns: repeat(2, 1fr); }
    .kpi-card:last-child { grid-column: span 2; }
    .kpi-label { white-space: normal; }
}
</style>
<div class="kpi-grid">"""
    + _cards
    + "</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("Data")
    mtime = cache_mtime()
    if mtime:
        import datetime

        updated = datetime.datetime.fromtimestamp(mtime).strftime("%b %d, %Y")
        st.caption(f"Snapshot from {updated}")
    st.caption("Use 🔄 Refresh data at the top of the page for the latest city data.")

# --- Shared filters, carried in the URL --------------------------------
# One filter set feeds every view (Map / List / Ask). The catch: the
# bottom nav switches views through plain ?view= links, and following
# one reloads the app in a fresh Streamlit session — which would reset
# every filter widget to its default and silently drop the user's
# selections. So widgets initialise from the URL, and the nav links at
# the bottom are rebuilt on every run carrying any non-default
# selection with them. Pick Bangladeshi on Map, tap List, and the List
# shows only Bangladeshi — and the same back again.
_QP_NONE = "__none__"


def _qp_selection(key, valid):
    """URL-stored selection for `key`: None if absent, else a list
    (empty list means the user explicitly selected nothing)."""
    try:
        present = key in st.query_params
    except Exception:
        present = False
    if not present:
        return None
    raw = list(st.query_params.get_all(key))
    if _QP_NONE in raw:
        return []
    valid_set = set(valid)
    return [v for v in raw if v in valid_set]


def _qp_text(key) -> str:
    values = list(st.query_params.get_all(key))
    return values[0] if values else ""


with st.expander("🔍 Filters", expanded=False):
    f1, f2 = st.columns(2)
    with f1:
        boroughs = sorted(df["boro"].dropna().unique())
        _init_boro = _qp_selection("boro", boroughs)
        sel_boro = st.multiselect(
            "Borough", boroughs,
            default=_init_boro if _init_boro is not None else boroughs,
        )
        _init_grade = _qp_selection("grade", ["A", "B", "C"])
        sel_grade = st.multiselect(
            "Grade", ["A", "B", "C"],
            default=_init_grade if _init_grade is not None else ["A", "B", "C"],
        )
        _init_tier = _qp_selection("tier", ["confirmed", "likely"])
        sel_tier = st.multiselect(
            "Halal confidence",
            ["confirmed", "likely"],
            default=_init_tier if _init_tier is not None else ["confirmed", "likely"],
            format_func=lambda t: TIER_BADGE[t],
        )
    with f2:
        # Drop missing first: on pandas 3.x astype(str) leaves float NaN
        # untouched, so stringify only after notna().
        zip_all = df["zipcode"]
        zip_all = zip_all[zip_all.notna()].astype(str).str.strip()
        zip_all = zip_all[~zip_all.str.lower().isin(["none", "<na>", ""])]
        zip_codes = sorted(zip_all.unique())
        _init_zip = _qp_selection("zip", zip_codes)
        sel_zip = st.multiselect(
            "ZIP code", zip_codes,
            default=_init_zip if _init_zip is not None else zip_codes,
        )
        cuisines = sorted(df["cuisine_description"].dropna().unique())
        _init_cuisine = _qp_selection("cuisine", cuisines)
        sel_cuisine = st.multiselect(
            "Cuisine", cuisines,
            default=_init_cuisine if _init_cuisine is not None else [],
        )
        query = st.text_input("Search by name", value=_qp_text("q"))
    st.caption("Tip: grades run A (best) → C. Lower inspection score = cleaner.")

view = df[df["boro"].isin(sel_boro)]
view = view[view["zipcode"].astype(str).str.strip().isin(sel_zip)]
view = view[view["grade"].isin(sel_grade) | view["grade"].isna()]
view = view[view["halal_tier"].isin(sel_tier)]
if sel_cuisine:
    view = view[view["cuisine_description"].isin(sel_cuisine)]
if query:
    view = view[view["dba"].str.contains(query, case=False, na=False)]
view = view.sort_values("score")

current = st.query_params.get("view", "map")
if current not in VIEWS:
    current = "map"

if current == "map":
    st.subheader(f"🗺️ {len(view)} spots")
    map_df = view.dropna(subset=["latitude", "longitude"]).copy()
    if not map_df.empty:
        import pydeck as pdk

        map_df["grade_display"] = map_df["grade"].fillna("–")
        map_df["tier_badge"] = map_df["halal_tier"].map(TIER_BADGE)
        map_df["pin_color"] = map_df["halal_tier"].map(TIER_COLOR)
        layer = pdk.Layer(
            "ScatterplotLayer",
            data=map_df,
            get_position=["longitude", "latitude"],
            get_radius=150,
            get_color="pin_color",
            pickable=True,
        )
        # Explicit view over NYC — st.map's auto-centering can render
        # blank on first load; this always shows the dots immediately.
        view_state = pdk.ViewState(latitude=40.7128, longitude=-74.0060, zoom=10)
        st.pydeck_chart(
            pdk.Deck(
                layers=[layer],
                initial_view_state=view_state,
                tooltip={"text": "{dba}\n{tier_badge} · {boro} · Grade {grade_display}"},
            )
        )
    else:
        st.info("No locations to show for these filters.")
elif current == "list":
    st.subheader(f"📋 {len(view)} spots")
    if "list_n" not in st.session_state:
        st.session_state.list_n = 12
    shown = st.session_state.list_n
    if view.empty:
        st.info("No spots match these filters.")
    else:
        cards_html = "".join(_restaurant_card(r) for _, r in view.head(shown).iterrows())
        st.markdown(
            CARD_CSS + '<div class="rlist">' + cards_html + "</div>",
            unsafe_allow_html=True,
        )
    if len(view) > shown:
        if st.button(f"Show more ({len(view) - shown} remaining)"):
            st.session_state.list_n = shown + 12
            st.rerun()
else:  # ask
    st.subheader("Ask in plain English")
    st.caption(
        "Try: 'best graded halal in Queens' · 'halal Indian food' · "
        "'halal spots in Brooklyn with grade A'"
    )
    if not concierge.llm_available:
        st.info(
            "Keyword mode: set OPENAI_API_KEY for full AI understanding. "
            "The agent still works — it just matches keywords instead."
        )
    if "messages" not in st.session_state:
        st.session_state.messages = []
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
    if question := st.chat_input("Where should I eat?"):
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        answer = concierge.ask(question)
        st.session_state.messages.append({"role": "assistant", "content": answer})
        with st.chat_message("assistant"):
            st.markdown(answer)

# Spacer so the fixed bottom nav never covers content.
st.markdown("<div style='height:90px'></div>", unsafe_allow_html=True)

# Nav links carry the current filter selections (see the note above the
# Filters expander) so switching tabs never drops them. Only non-default
# selections are encoded, to keep the URL short.
_filter_params: dict[str, list[str]] = {}


def _carry(key, selected, full):
    sel_list = list(selected)
    if set(sel_list) == set(full):
        return  # default (everything selected) — nothing to carry
    _filter_params[key] = sel_list if sel_list else [_QP_NONE]


_carry("boro", sel_boro, boroughs)
_carry("grade", sel_grade, ["A", "B", "C"])
_carry("tier", sel_tier, ["confirmed", "likely"])
_carry("zip", sel_zip, zip_codes)
if sel_cuisine:
    _filter_params["cuisine"] = list(sel_cuisine)
if query:
    _filter_params["q"] = [query]


def _nav_href(view_key: str) -> str:
    params = {**_filter_params, "view": view_key}
    if st.session_state.get("theme") == "light":
        params["theme"] = ["light"]
    return "?" + urlencode(params, doseq=True)


nav_links = "".join(
    f'<a href="{_nav_href(key)}" target="_self"'
    f' class="{"active" if key == current else ""}">{label}</a>'
    for key, label in VIEWS.items()
)
st.markdown(
    """
<style>
.bottom-nav {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 999;
    display: flex;
    justify-content: space-around;
    align-items: center;
    padding: 10px 8px calc(10px + env(safe-area-inset-bottom));
    background: rgba(127, 127, 127, 0.14);
    -webkit-backdrop-filter: blur(14px);
    backdrop-filter: blur(14px);
    border-top: 1px solid rgba(127, 127, 127, 0.35);
}
.bottom-nav a {
    text-decoration: none;
    color: inherit;
    font-size: 14px;
    padding: 8px 22px;
    border-radius: 999px;
    text-align: center;
}
.bottom-nav a.active {
    background: rgba(255, 75, 43, 0.16);
    color: #ff4b2b;
    font-weight: 800;
}
</style>
<div class="bottom-nav">"""
    + nav_links
    + """</div>""",
    unsafe_allow_html=True,
)

st.divider()
st.caption(
    "Data: NYC Open Data · DOHMH Restaurant Inspection Results. "
    "🟢 confirmed halal (name/cuisine says halal) · "
    "🟡 likely halal by cuisine — verify before visiting."
)
