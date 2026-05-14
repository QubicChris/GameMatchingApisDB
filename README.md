# Pregames Snapshot API

A football (soccer) pregame data ingestion and analysis platform. It ingests batched snapshots of game data from an upstream system — including bookmaker odds, markets, and live scores — stores them in a MySQL database, enriches them by matching to Sofasport events, and exposes a REST API and visual dashboard for browsing and validating the data.

---

## Features

- **Ingest** hourly JSON snapshots from an upstream system with full odds, markets, and selections
- **Enrich** games by fuzzy-matching them to Sofasport events and pulling in closing odds and match statistics
- **Explore** data via a FastAPI REST API (with auto-generated docs) and a Streamlit dashboard
- **Validate** DB integrity with a built-in test suite
- **Replay** historical payloads or reload saved Sofasport API responses without re-calling the API

---

## Architecture

```
[Upstream System] ──POST /ingest──► [FastAPI]
                                        │
                              upserts games / company_games /
                              markets / selections into MySQL
                                        │
                              optionally saves raw payload JSON

[Scripts]
  plan_sofa_calls.py   → preview what Sofasport API calls are needed
  batch_match_sofa.py  → fuzzy-match DB games to Sofasport, fetch odds + stats
  load_sofa_json.py    → reload saved Sofasport responses into DB (no API calls)
  send_payloads.py     → replay saved payload files to /ingest

[UI]
  streamlit run dashboard.py  → browse games, odds, stats, team aliases
```

---

## Database Schema

```
games
 ├── company_games       (one per bookmaker)
 │    └── pregame_markets (one per market type)
 │         └── selections (one per outcome / line)
 ├── sofa_games          (Sofasport event record)
 ├── sofa_odds           (Sofasport closing odds)
 └── sofa_statistics     (match stats: possession, xG, shots, etc.)
team_aliases             (bookmaker name → canonical name)
market_types             (umid → market name lookup)
```

---

## Requirements

- Python 3.10+
- MySQL 8+
- A [RapidAPI](https://rapidapi.com) account with access to the **Sofasport** API

---

## Setup

### 1. Clone and create a virtual environment

```powershell
git clone <repo-url>
cd GameMatchingApisDB
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
pip install rapidfuzz streamlit pandas requests
```

### 3. Create a `.env` file

```ini
# Required
DATABASE_URL=mysql+pymysql://user:password@localhost:3306/pregames
RAPIDAPI_KEY=your_rapidapi_key_here

# Optional
ODDS_PROVIDER_ID=1          # Sofasport odds provider (1 = Bet365, default)
SAVE_FAILED_PAYLOADS=true   # Save payloads that fail validation (default: true)
SAVE_ALL_PAYLOADS=false     # Save every incoming payload (default: false)
```

---

## Running the API

```powershell
uvicorn main:app --host 0.0.0.0 --port 9998 --reload
```

Tables are auto-created on first startup.  
Interactive API docs: `http://localhost:9998/docs`

### Key endpoints

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/ingest` | Ingest a JSON array of game snapshots |
| `GET` | `/games` | List games (filter by league, paginate) |
| `GET` | `/games/{id}` | Full game detail with markets and selections |
| `GET` | `/health` | Health check |

---

## Running the Dashboard

```powershell
streamlit run dashboard.py --server.port 9996 --server.address 0.0.0.0
```

Pages:
- **Games** — filter by date / country / Sofasport match status; view odds comparison and match stats
- **Team Aliases** — how each bookmaker names each team
- **Market Types** — all known market IDs and their canonical names

---

## Sofascore Matching Scripts

### Preview API calls (no requests made)

```powershell
python plan_sofa_calls.py --date 2026-05-14
```

### Run batch matching for a date

```powershell
python batch_match_sofa.py --date 2026-05-14
```

Flags:

| Flag | Description |
|------|-------------|
| `--dry-run` | Preview matches without writing to DB |
| `--unmatched-only` | Only process games without a Sofasport match |
| `--min-confidence N` | Skip matches below this fuzzy score (default: 55) |
| `--min-games N` | Skip countries with fewer than N games |

### Reload saved Sofasport data (no API calls)

```powershell
python load_sofa_json.py --date 2026-05-14
python load_sofa_json.py --date 2026-05-14 --dry-run
```

### Replay saved payload files

```powershell
python send_payloads.py
```

---

## Database Tests

```powershell
python test_db.py
```

Runs 15 integrity checks including duplicate detection, orphaned records, NULL odds, structural market rules (Match Result must have 3 selections, O/U must have both sides), and negative scores.

---

## Project Structure

```
├── main.py                   FastAPI application and ingest logic
├── models.py                 SQLAlchemy ORM models
├── schemas.py                Pydantic request/response schemas
├── database.py               DB engine, session, and init
├── normalizer.py             Selection outcome normalizer (Usn codes → canonical)
├── batch_match_sofa.py       Batch Sofasport matching (main enrichment script)
├── match_sofa.py             Single-country matching (diagnostic/interactive)
├── plan_sofa_calls.py        Dry-run planner for Sofasport API calls
├── load_sofa_json.py         Offline loader for saved Sofasport responses
├── send_payloads.py          Replay saved payload files to /ingest
├── dashboard.py              Streamlit data browser
├── test_db.py                DB integrity test suite
├── test_ingest.py            Basic ingest smoke test
├── payloads/                 Payloads saved by the API (failed or all)
├── payloads2/, payloads3/    Historical snapshot batches from upstream
└── sofa_calls/               Saved Sofasport API responses by date
```

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | SQLAlchemy connection string |
| `RAPIDAPI_KEY` | Yes | — | RapidAPI key for Sofasport |
| `ODDS_PROVIDER_ID` | No | `1` | Sofasport odds provider (1 = Bet365) |
| `SAVE_FAILED_PAYLOADS` | No | `true` | Save payloads that fail validation |
| `SAVE_ALL_PAYLOADS` | No | `false` | Save every incoming payload |
