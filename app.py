"""Halal NYC Finder — Streamlit app.

Run:  streamlit run app.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from urllib.parse import urlencode

import pandas as pd
import streamlit as st

from agent import Concierge
from data import cache_mtime, load
from halal import TIER_BADGE, TIER_COLOR, TIER_NOTE, add_address, add_match_reason, grade_label

st.set_page_config(page_title="Halal NYC Finder", page_icon="🍽️", layout="wide")

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


@st.cache_data(show_spinner="Loading NYC restaurant data…")
def get_data() -> pd.DataFrame:
    df = load()
    df = add_match_reason(df)
    df = add_address(df)
    return df


df = get_data()
concierge = Concierge(df)

n_confirmed = int((df["halal_tier"] == "confirmed").sum())
n_likely = int((df["halal_tier"] == "likely").sum())

st.title("🍽️ Halal NYC Finder")
st.caption(
    f"{n_confirmed} confirmed halal · {n_likely} likely halal spots across NYC · "
    "NYC Open Data (DOHMH inspections) · hygiene grades included"
)
st.caption(TIER_NOTE)

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
# Color discipline: green/amber already mean halal tier on this page
# (map pins + badges: green = confirmed, amber = likely), so the KPI
# strip uses NO grade traffic-light colors and no colored dots — one
# uniform neutral accent for every card, and the grade letter in the
# label carries the meaning. A color must mean one thing per screen.
_kpis = [
    ("Total spots", _total, "across NYC"),
    ("Grade A", _n_a, _pct(_n_a)),
    ("Grade B", _n_b, _pct(_n_b)),
    ("Grade C", _n_c, _pct(_n_c)),
    ("Not yet graded", _n_not_graded, _pct(_n_not_graded)),
]
_cards = "".join(
    '<div class="kpi-card">'
    f'<div class="kpi-label">{label}</div>'
    f'<div class="kpi-value">{value:,}</div>'
    f'<div class="kpi-sub">{sub}</div></div>'
    for label, value, sub in _kpis
)
st.markdown(
    """
<style>
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 8px;
    margin: 4px 0 12px 0;
}
.kpi-card {
    border: 1px solid rgba(128, 128, 128, 0.28);
    border-top: 3px solid #64748b;
    border-radius: 12px;
    padding: 10px 12px 8px 12px;
    background: rgba(128, 128, 128, 0.07);
    min-width: 0;
}
.kpi-label {
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
    font-size: clamp(20px, 5vw, 28px);
    font-weight: 800;
    line-height: 1.15;
}
.kpi-sub { font-size: 12px; opacity: 0.7; white-space: nowrap; }
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
    if st.button("🔄 Refresh data"):
        with st.spinner("Fetching the latest from NYC Open Data…"):
            load(refresh=True)
            st.cache_data.clear()
        st.rerun()

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
    for _, r in view.head(shown).iterrows():
        score = int(r["score"]) if pd.notna(r["score"]) else "—"
        with st.container(border=True):
            name_col, grade_col = st.columns([5, 1.5])
            with name_col:
                st.markdown(f"**{r['dba'].title()}**")
            with grade_col:
                st.markdown(
                    grade_pill(r["grade"], r.get("grade_detail")),
                    unsafe_allow_html=True,
                )
            st.caption(f"{r['address']}")
            st.caption(
                f"{TIER_BADGE[r['halal_tier']]} · {r['cuisine_description']} · "
                f"Inspection score {score} (lower is better)"
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
    return "?" + urlencode({**_filter_params, "view": view_key}, doseq=True)


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
