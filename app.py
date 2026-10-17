"""Halal NYC Finder — Streamlit app.

Run:  streamlit run app.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

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


def grade_pill(grade: str) -> str:
    """Colored grade badge for the list cards (Zabihah-style)."""
    if grade in GRADE_STYLE:
        return (
            f'<span style="{GRADE_STYLE[grade]}padding:3px 12px;'
            'border-radius:999px;font-weight:800;font-size:14px;'
            f'white-space:nowrap;">Grade {grade}</span>'
        )
    return (
        '<span style="background:#6c757d;color:#fff;padding:3px 12px;'
        'border-radius:999px;font-size:13px;white-space:nowrap;">Not graded</span>'
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

    st.divider()
    st.subheader("Filters")
    boroughs = sorted(df["boro"].dropna().unique())
    sel_boro = st.multiselect("Borough", boroughs, default=boroughs)
    # Drop missing first: on pandas 3.x astype(str) leaves float NaN
    # untouched, so stringify only after notna().
    zip_all = df["zipcode"]
    zip_all = zip_all[zip_all.notna()].astype(str).str.strip()
    zip_all = zip_all[~zip_all.str.lower().isin(["none", "<na>", ""])]
    zip_codes = sorted(zip_all.unique())
    sel_zip = st.multiselect("ZIP code", zip_codes, default=zip_codes)
    sel_grade = st.multiselect("Grade", ["A", "B", "C"], default=["A", "B", "C"])
    sel_tier = st.multiselect(
        "Halal confidence",
        ["confirmed", "likely"],
        default=["confirmed", "likely"],
        format_func=lambda t: TIER_BADGE[t],
    )
    cuisines = sorted(df["cuisine_description"].dropna().unique())
    sel_cuisine = st.multiselect("Cuisine", cuisines)
    query = st.text_input("Search by name")
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
                st.markdown(grade_pill(r["grade"]), unsafe_allow_html=True)
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

nav_links = "".join(
    f'<a href="?view={key}" target="_self"'
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
