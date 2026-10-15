# 🍽️ Halal NYC Finder

Find Halal restaurants across New York City — with hygiene grades, an interactive
map, and an **AI concierge** you can ask in plain English.

Built as a portfolio project combining **data science, data visualization, and
agentic AI** on public data.

## What it does

- 🗺️ **Explore** — filter 169 Halal restaurants by borough, hygiene grade,
  cuisine, or name; see them on a map with inspection scores.
- 💬 **Ask the concierge** — a conversational AI agent: *"best graded halal in
  Queens"*, *"halal Indian food in Brooklyn"*. The agent turns plain English
  into structured filters and answers with real data.

## Data

NYC Open Data — [DOHMH Restaurant Inspection Results](https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j)
(~297k inspection records). The pipeline keeps the latest inspection per
restaurant and normalizes grades, scores, and coordinates.

> **Known limitation:** the city publishes no "halal" flag, so Halal spots are
> identified when the word appears in the business name or cuisine description.
> This undercounts (many Halal carts never register the word). Future work:
> expand via cuisine families (Middle Eastern, Bangladeshi, Pakistani, Turkish…).

## How the AI agent works

A **text-to-structured-query** pattern (no arbitrary code execution):

1. Your question goes to an LLM with the dataset schema.
2. The LLM returns a small JSON filter spec (borough, grade, cuisine, …).
3. Python applies the filters deterministically and formats the answer.

Without an API key the concierge falls back to keyword matching, so the demo
always works.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Optional — full AI understanding:

```bash
export OPENAI_API_KEY=sk-...        # any OpenAI-compatible key
export OPENAI_BASE_URL=...          # optional, for compatible providers
export OPENAI_MODEL=gpt-4o-mini     # optional
```

## Project structure

```
├── app.py            # Streamlit dashboard + chat UI
├── src/
│   ├── data.py       # Socrata fetch, cleaning, latest-inspection dedupe
│   ├── halal.py      # Halal identification heuristic + address formatting
│   └── agent.py      # Concierge: LLM filter-spec + deterministic execution
└── data/             # cached parquet (built on first run, gitignored)
```

## Tech

Python · pandas · Streamlit · NYC Open Data (Socrata API) · OpenAI-compatible LLMs
