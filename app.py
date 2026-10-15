"""Halal NYC Finder — Streamlit app.

Run:  streamlit run app.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import pandas as pd
import streamlit as st

from agent import Concierge
from data import load
from halal import add_address, add_match_reason, grade_label

st.set_page_config(page_title="Halal NYC Finder", page_icon="🍽️", layout="wide")


@st.cache_data(show_spinner="Loading NYC restaurant data…")
def get_data() -> pd.DataFrame:
    df = load()
    df = add_match_reason(df)
    df = add_address(df)
    return df


df = get_data()
concierge = Concierge(df)

st.title("🍽️ Halal NYC Finder")
st.caption(
    f"{len(df)} Halal restaurants across NYC · "
    "NYC Open Data (DOHMH inspections) · hygiene grades included"
)

tab_map, tab_chat = st.tabs(["🗺️ Explore", "💬 Ask the concierge"])

with tab_map:
    col1, col2 = st.columns([1, 3])
    with col1:
        st.subheader("Filters")
        boroughs = sorted(df["boro"].dropna().unique())
        sel_boro = st.multiselect("Borough", boroughs, default=boroughs)
        sel_grade = st.multiselect("Grade", ["A", "B", "C"], default=["A", "B", "C"])
        cuisines = sorted(df["cuisine_description"].dropna().unique())
        sel_cuisine = st.multiselect("Cuisine", cuisines)
        query = st.text_input("Search by name")
        st.caption("Tip: grades run A (best) → C. Lower inspection score = cleaner.")

    view = df[df["boro"].isin(sel_boro)]
    view = view[view["grade"].isin(sel_grade) | view["grade"].isna()]
    if sel_cuisine:
        view = view[view["cuisine_description"].isin(sel_cuisine)]
    if query:
        view = view[view["dba"].str.contains(query, case=False, na=False)]
    view = view.sort_values("score")

    with col2:
        st.subheader(f"{len(view)} spots")
        map_df = view.dropna(subset=["latitude", "longitude"]).rename(
            columns={"latitude": "lat", "longitude": "lon"}
        )
        if not map_df.empty:
            st.map(map_df[["lat", "lon"]], zoom=10)
        for _, r in view.head(25).iterrows():
            with st.expander(f"{r['dba'].title()} — {r['boro']} · Grade {grade_label(r['grade'])}"):
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
    "Halal spots are identified when 'halal' appears in the business name or cuisine — "
    "an undercount, documented in the README."
)
