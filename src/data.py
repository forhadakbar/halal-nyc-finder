"""Data pipeline: fetch NYC restaurant inspection records from the
NYC Open Data Socrata API and build a clean Halal-restaurant dataset.

Source: DOHMH New York City Restaurant Inspection Results
https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j
"""
from __future__ import annotations

import json
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
REQUIRED_COLUMNS = {"halal_tier", "grade_detail", "violations_json", "history_json"}

# Socrata allows 1000 rows per request for unauthenticated callers.
PAGE_SIZE = 1000
MAX_PAGES = 40  # safety cap; ~1.7k halal records expected

FIELDS = [
    "camis", "dba", "boro", "building", "street", "zipcode", "phone",
    "cuisine_description", "inspection_date", "inspection_type", "action",
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

    df["_has_grade"] = df["grade"].notna().astype(int)

    # --- Grade-details payload, built BEFORE the dedupe below throws the
    # other inspection rows away (each Socrata row is one violation within
    # an inspection; an inspection = camis + inspection_date).
    #   violations_json: violations cited at the inspection that ends up
    #     chosen for the card, so "Grade details" can show *why* the grade.
    #   history_json: up to 8 past inspections (date, grade, score, type)
    #     per restaurant.
    # Stored as JSON strings: plain str columns survive parquet round-trips
    # on every pandas version (list/struct columns have bitten us before).
    df["insp_date"] = df["inspection_date"].dt.strftime("%Y-%m-%d").fillna("nodate")
    df["insp_key"] = df["camis"] + "|" + df["insp_date"]

    viol = df[
        df["violation_description"].notna()
        & (df["violation_description"].str.strip() != "")
    ]
    viol_by_insp: dict[str, str] = {}
    if not viol.empty:
        per_desc = (
            viol.assign(_crit=(viol["critical_flag"] == "Critical").astype(int))
            .groupby(["insp_key", "violation_description"], as_index=False)
            .agg(critical=("_crit", "max"), code=("violation_code", "first"))
        )
        for insp, grp in per_desc.groupby("insp_key"):
            items = [
                {
                    "desc": str(r.violation_description).strip(),
                    "critical": bool(r.critical),
                    "code": "" if pd.isna(r.code) else str(r.code),
                }
                for r in grp.itertuples()
            ]
            # Critical violations first — they're what a reader scans for.
            items.sort(key=lambda v: not v["critical"])
            viol_by_insp[insp] = json.dumps(items)

    rep = (
        df.sort_values(["camis", "insp_date", "_has_grade"])
        .drop_duplicates(["camis", "insp_date"], keep="last")
        .sort_values(["camis", "insp_date"], ascending=[True, False])
    )
    hist_by_camis: dict[str, str] = {}
    for camis, grp in rep.groupby("camis"):
        entries = []
        for r in grp.head(8).itertuples():
            if r.insp_date == "nodate":
                continue
            entries.append(
                {
                    "date": r.insp_date,
                    "grade": None if pd.isna(r.grade) else str(r.grade),
                    "detail": None if pd.isna(r.grade_detail) else str(r.grade_detail),
                    "score": None if pd.isna(r.score) else float(r.score),
                    "type": None
                    if pd.isna(getattr(r, "inspection_type", None))
                    else str(r.inspection_type),
                }
            )
        hist_by_camis[camis] = json.dumps(entries)

    # Latest inspection per restaurant wins — but prefer the most recent
    # *graded* inspection so grade/score aren't empty when a grade exists.
    df = (
        df.sort_values(["camis", "_has_grade", "inspection_date"])
        .drop_duplicates("camis", keep="last")
        .drop(columns="_has_grade")
    )
    df["violations_json"] = df["insp_key"].map(viol_by_insp).fillna("[]")
    df["history_json"] = df["camis"].map(hist_by_camis).fillna("[]")
    df = df.drop(columns=["insp_key", "insp_date"])
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
