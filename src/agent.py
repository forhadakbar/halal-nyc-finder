"""Halal NYC Concierge — a natural-language agent over the restaurant data.

How it works (text-to-structured-query pattern):
  1. The user's plain-English question goes to an LLM with a description
     of the dataset and the allowed filter fields.
  2. The LLM returns a small JSON filter spec — never raw code.
  3. Python applies the filters deterministically and formats the answer.

This keeps the LLM away from arbitrary code execution while still giving
a conversational experience. Without an API key the concierge falls back
to a keyword matcher so the demo still works.

Configure with environment variables:
  OPENAI_API_KEY  — any OpenAI-compatible key
  OPENAI_BASE_URL — optional (for OpenAI-compatible providers)
  OPENAI_MODEL    — optional, defaults to gpt-4o-mini
"""
from __future__ import annotations

import json
import os
import re

import pandas as pd

BOROUGHS = ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]
GRADES = ["A", "B", "C"]

SYSTEM_PROMPT = """You help people find Halal restaurants in New York City.
You answer by emitting a JSON filter object — nothing else.

Dataset columns you may filter on:
- boro: one of ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]
- grade: one of ["A", "B", "C"] (NYC hygiene grade; A is best)
- max_score: number; lower inspection score is better (0 is perfect)
- cuisine: free text matched against cuisine_description (e.g. "Indian", "Middle Eastern")
- name: free text matched against the restaurant name
- min_grade: "A" means only A; "B" means A or B; "C" means A, B or C
- sort_by: one of ["score", "name"] (score = best hygiene first)
- limit: max results, default 5, never more than 10

Examples:
- "halal spots in Queens" -> {"boro": "Queens", "limit": 5}
- "best graded halal in Brooklyn" -> {"boro": "Brooklyn", "min_grade": "A", "sort_by": "score", "limit": 5}
- "halal indian food" -> {"cuisine": "Indian", "limit": 5}
- "find Shah's Halal" -> {"name": "Shah's", "limit": 5}

Rules:
- Output ONLY the JSON object. No prose, no markdown fences.
- If the question is not about finding restaurants, output {"unrelated": true}.
"""


def _llm_filter(question: str) -> dict | None:
    """Ask the LLM to turn the question into a filter spec."""
    try:
        from openai import OpenAI
    except ImportError:
        return None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        client = OpenAI(
            api_key=api_key,
            base_url=os.environ.get("OPENAI_BASE_URL") or None,
        )
        resp = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=0,
            max_tokens=200,
        )
        text = resp.choices[0].message.content.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text).strip()
        return json.loads(text)
    except Exception:
        return None


def _keyword_filter(question: str) -> dict:
    """Fallback when no LLM is configured: borough + cuisine + name keywords."""
    q = question.lower()
    spec: dict = {"limit": 5}
    m = re.match(r"(?:find|search for|look for)\s+(.+)", q)
    if m:
        spec["name"] = m.group(1).strip().title()
        return spec
    for b in BOROUGHS:
        if b.lower() in q:
            spec["boro"] = b
    if "best graded" in q or "best" in q:
        spec["min_grade"] = "A"
    m = re.search(r"(indian|pakistani|bangladeshi|middle eastern|turkish|moroccan|egyptian|afghan|malaysian|indonesian|chinese)", q)
    if m:
        spec["cuisine"] = m.group(1).title()
    if "best" in q or "top" in q or "graded" in q:
        spec["sort_by"] = "score"
    return spec


def apply_filters(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    out = df.copy()
    if spec.get("boro"):
        out = out[out["boro"].str.lower() == str(spec["boro"]).lower()]
    if spec.get("min_grade"):
        order = {"A": ["A"], "B": ["A", "B"], "C": ["A", "B", "C"]}
        out = out[out["grade"].isin(order.get(spec["min_grade"], GRADES))]
    if spec.get("max_score") is not None:
        out = out[out["score"] <= float(spec["max_score"])]
    if spec.get("cuisine"):
        out = out[out["cuisine_description"].str.contains(str(spec["cuisine"]), case=False, na=False)]
    if spec.get("name"):
        out = out[out["dba"].str.contains(str(spec["name"]), case=False, na=False)]
    if spec.get("sort_by") == "score":
        out = out.sort_values("score")
    elif spec.get("sort_by") == "name":
        out = out.sort_values("dba")
    return out.head(int(spec.get("limit", 5)))


def format_answer(rows: pd.DataFrame) -> str:
    if rows.empty:
        return "I couldn't find a Halal spot matching that. Try a different borough or cuisine!"
    lines = []
    for _, r in rows.iterrows():
        grade = r["grade"] if r["grade"] in GRADES else "ungraded"
        score = f"score {int(r['score'])}" if pd.notna(r["score"]) else "no score"
        lines.append(
            f"• **{r['dba'].title()}** — {r['boro']}, grade {grade} ({score})\n"
            f"  {r.get('address', '')} · {r.get('cuisine_description', '')}"
        )
    return "\n".join(lines)


class Concierge:
    """The conversational agent. Call .ask(question) with plain English."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.llm_available = bool(os.environ.get("OPENAI_API_KEY"))

    def ask(self, question: str) -> str:
        spec = _llm_filter(question)
        if spec is None:
            spec = _keyword_filter(question)
        if spec.get("unrelated"):
            return (
                "I help you find Halal restaurants in NYC — try something like "
                "'best graded halal in Queens' or 'halal Indian food in Brooklyn'."
            )
        rows = apply_filters(self.df, spec)
        header = "" if self.llm_available else "_Keyword mode (add an API key for full AI understanding)._ \n"
        return header + format_answer(rows)
