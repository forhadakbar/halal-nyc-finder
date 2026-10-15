"""Halal identification helpers.

The city's inspection data has no "halal" flag, so we identify Halal
restaurants with a transparent, documented heuristic: the word "halal"
appears in the business name (dba) or the cuisine description.

This is deliberately conservative — many Halal carts and restaurants never
put the word in their registered name, so the dataset undercounts. The
README documents this as a known limitation and a future improvement
(cuisine-based expansion: Middle Eastern, Bangladeshi, Pakistani, Turkish…).
"""
from __future__ import annotations

import pandas as pd


def match_reason(row: pd.Series) -> str:
    name_hit = "halal" in str(row.get("dba", "")).lower()
    cuisine_hit = "halal" in str(row.get("cuisine_description", "")).lower()
    if name_hit and cuisine_hit:
        return "name + cuisine"
    if name_hit:
        return "name"
    if cuisine_hit:
        return "cuisine"
    return "unknown"


def add_match_reason(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["halal_match"] = df.apply(match_reason, axis=1)
    return df


def address(row: pd.Series) -> str:
    parts = [str(row.get("building", "")).strip(), str(row.get("street", "")).strip()]
    street = " ".join(p for p in parts if p and p.lower() != "nan")
    city = str(row.get("boro", "")).strip()
    zipc = str(row.get("zipcode", "")).strip()
    bits = [street, city]
    if zipc and zipc.lower() != "nan":
        bits.append(f"NY {zipc}")
    return ", ".join(b for b in bits if b)


def add_address(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["address"] = df.apply(address, axis=1)
    return df


def grade_label(grade) -> str:
    return grade if grade in ("A", "B", "C") else "Not graded"


TIER_BADGE = {
    "confirmed": "🟢 Confirmed halal",
    "likely": "🟡 Likely halal",
}

TIER_NOTE = "🟡 = likely halal by cuisine — please verify before visiting."


def tier_badge(tier: str) -> str:
    return TIER_BADGE.get(tier, tier)


# Map pin colors by tier: green = confirmed, amber = likely.
TIER_COLOR = {
    "confirmed": [40, 170, 90],
    "likely": [230, 170, 40],
}
