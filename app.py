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


@st.cache_data(show_spinner="Loading NYC restaurant data…")
def get_data() -> pd.DataFrame:
    df = load()
    df = add_match_reason(df)
    df = add_address(df)
    return df


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

tab_map, tab_chat = st.tabs(["🗺️ Explore", "💬 Ask the concierge"])

with tab_map:
    col1, col2 = st.columns([1, 3])
    with col1:
        st.subheader("Filters")
        boroughs = sorted(df["boro"].dropna().unique())
        sel_boro = st.multiselect("Borough", boroughs, default=boroughs)
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
    view = view[view["grade"].isin(sel_grade) | view["grade"].isna()]
    view = view[view["halal_tier"].isin(sel_tier)]
    if sel_cuisine:
        view = view[view["cuisine_description"].isin(sel_cuisine)]
    if query:
        view = view[view["dba"].str.contains(query, case=False, na=False)]
    view = view.sort_values("score")

    with col2:
        st.subheader(f"{len(view)} spots")
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
        for _, r in view.head(25).iterrows():
            with st.expander(
                f"{TIER_BADGE[r['halal_tier']].split(' ', 1)[0]} {r['dba'].title()} — "
                f"{r['boro']} · Grade {grade_label(r['grade'])}"
            ):
                st.write(f"**Address:** {r['address']}")
                st.write(f"**Cuisine:** {r['cuisine_description']}")
                score = int(r["score"]) if pd.notna(r["score"]) else "—"
                st.write(f"**Inspection score:** {score} (lower is better)")
                if pd.notna(r["inspection_date"]):
                    st.write(f"**Last inspected:** {r['inspection_date'].date()}")
                if r["phone"] and str(r["phone"]) != "nan":
                    st.write(f"**Phone:** {r['phone']}")

with tab_chat:
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

st.divider()
st.caption(
    "Data: NYC Open Data · DOHMH Restaurant Inspection Results. "
    "🟢 confirmed halal (name/cuisine says halal) · "
    "🟡 likely halal by cuisine — verify before visiting."
)
