"""Data pipeline: fetch NYC restaurant inspection records from the
NYC Open Data Socrata API and build a clean Halal-restaurant dataset.

Source: DOHMH New York City Restaurant Inspection Results
https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j
"""
from __future__ import annotations

import os
import time

import pandas as pd
import requests

API_URL = "https://data.cityofnewyork.us/resource/43nn-pn8j.json"
CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "halal_restaurants.parquet")

# Columns the cached snapshot must have. When the pipeline gains a new
# column, an old snapshot on disk (e.g. Streamlit Cloud's persistent
# filesystem) must be rebuilt, not trusted — otherwise the app crashes
# on startup with a KeyError.
REQUIRED_COLUMNS = {"halal_tier", "grade_detail"}

# Socrata allows 1000 rows per request for unauthenticated callers.
PAGE_SIZE = 1000
MAX_PAGES = 40  # safety cap; ~1.7k halal records expected

FIELDS = [
    "camis", "dba", "boro", "building", "street", "zipcode", "phone",
    "cuisine_description", "inspection_date", "action",
    "violation_code", "violation_description", "critical_flag",
    "score", "grade", "grade_date", "record_date",
    "latitude", "longitude",
]

HALAL_WHERE = (
    "upper(dba) like '%HALAL%' OR "
    "upper(cuisine_description) like '%HALAL%'"
)

# Cuisines where halal is the strong norm. These become the "likely halal"
# tier — clearly labeled as inference, not verification.
LIKELY_HALAL_CUISINES = [
    "Pakistani", "Bangladeshi", "Middle Eastern", "Turkish",
    "Afghan", "Moroccan", "Egyptian", "Indian", "Mediterranean",
]

HALAL_WHERE = (
    HALAL_WHERE
    + " OR upper(cuisine_description) in ("
    + ",".join(f"'{c.upper()}'" for c in LIKELY_HALAL_CUISINES)
    + ")"
)


def fetch_halal_inspections() -> pd.DataFrame:
    """Download every inspection record mentioning Halal (paginated)."""
    frames: list[pd.DataFrame] = []
    for page in range(MAX_PAGES):
        params = {
            "$select": ",".join(FIELDS),
            "$where": HALAL_WHERE,
            "$limit": PAGE_SIZE,
            "$offset": page * PAGE_SIZE,
            "$order": "camis",
        }
        resp = requests.get(API_URL, params=params, timeout=60)
        resp.raise_for_status()
        batch = pd.DataFrame(resp.json())
        if batch.empty:
            break
        frames.append(batch)
        if len(batch) < PAGE_SIZE:
            break
        time.sleep(0.3)  # be polite to the public API
    if not frames:
        return pd.DataFrame(columns=FIELDS)
    return pd.concat(frames, ignore_index=True)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize types, keep the latest inspection per restaurant (camis)."""
    df = df.copy()
    df["camis"] = df["camis"].astype(str)
    for col in ("score",):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("latitude", "longitude"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Scrub bad coordinates: (0,0) "Null Island" points and anything outside
    # the NYC area are data-entry errors. Null them so they can't distort the
    # map — the restaurants themselves stay in the table.
    in_nyc = df["latitude"].between(40.4, 41.0) & df["longitude"].between(-74.4, -73.5)
    df.loc[~in_nyc, ["latitude", "longitude"]] = float("nan")
    for col in ("inspection_date", "grade_date", "record_date"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    # Keep the raw non-letter grade (Z/P/N) so the UI can say *why* a
    # restaurant has no letter grade instead of a flat "Not graded".
    # N = not yet graded, Z/P = grade pending (DOHMH codes).
    df["grade_detail"] = df["grade"].mask(df["grade"].isin(["A", "B", "C"]))
    df["grade"] = df["grade"].where(df["grade"].isin(["A", "B", "C"]))
    df["boro"] = df["boro"].replace({"0": "Unknown"})

    # Two-tier halal labeling.
    #   confirmed: the word "halal" is in the name or cuisine — high precision.
    #   likely:    cuisine is one where halal is the strong norm (Pakistani,
    #              Bangladeshi, Middle Eastern, …) — broader recall, and the
    #              UI marks these "verify before visiting".
    name_hit = df["dba"].str.contains("halal", case=False, na=False)
    cuisine_hit = df["cuisine_description"].str.contains("halal", case=False, na=False)
    df["halal_tier"] = "likely"
    df.loc[name_hit | cuisine_hit, "halal_tier"] = "confirmed"

    # Latest inspection per restaurant wins — but prefer the most recent
    # *graded* inspection so grade/score aren't empty when a grade exists.
    df["_has_grade"] = df["grade"].notna().astype(int)
    df = (
        df.sort_values(["camis", "_has_grade", "inspection_date"])
        .drop_duplicates("camis", keep="last")
        .drop(columns="_has_grade")
    )
    df = df.reset_index(drop=True)
    return df


def load(refresh: bool = False) -> pd.DataFrame:
    """Load the cached dataset, fetching from the API on first run."""
    if not refresh and os.path.exists(CACHE_PATH):
        df = pd.read_parquet(CACHE_PATH)
        if REQUIRED_COLUMNS.issubset(df.columns):
            return df
        # Stale cache from before a pipeline change — rebuild instead of
        # crashing the app on a missing column.
    df = clean(fetch_halal_inspections())
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    df.to_parquet(CACHE_PATH, index=False)
    return df


def cache_mtime() -> float | None:
    """When the cached dataset was last fetched (epoch seconds), if cached."""
    if os.path.exists(CACHE_PATH):
        return os.path.getmtime(CACHE_PATH)
    return None


if __name__ == "__main__":
    df = load(refresh=True)
    print(f"{len(df)} halal restaurants")
    print(df[["dba", "boro", "grade", "score"]].head(10).to_string())
