# CRM Client Sync

Automated pipeline that reads a daily client update CSV from an external provider,
validates and cleans the data, and upserts records into a local SQLite database.
Replaces a manual daily copy-paste process with a file watcher that triggers the
sync automatically the moment a new CSV lands in the drop folder.

---

## Try it online

A live demo is deployed at:
**https://crm-client-sync.streamlit.app**

Upload `sample_data/client_updates_sample.csv` (included in this repo) to see
the full pipeline run in your browser with no setup required.

---

## Quick start (local)

```bash
git clone https://github.com/Abhirami-Mohanarangam/crm-client-sync.git
cd crm-client-sync
pip install -r requirements.txt

# Web UI -- upload a CSV and see results in the browser
streamlit run app.py

# One-off sync against the included sample file
python3 sync.py sample_data/client_updates_sample.csv

# Automated mode -- drop any CSV into watch/ and it syncs automatically
python3 watcher.py
```

After running `sync.py` or `watcher.py` you will have:
- `crm.db` -- SQLite database with cleaned client records
- `sync_log.txt` -- timestamped log of every issue found and every action taken

Open `crm.db` with [DB Browser for SQLite](https://sqlitebrowser.org) (free) to
browse the data and the audit tables.

---

## How it works

**watcher.py** monitors the `watch/` folder. When a CSV file lands there, it:

1. Calls `sync.py` to validate, clean, and upsert records into `crm.db`
2. Moves the processed file to `archive/` with a timestamp so nothing is lost
3. Logs everything to `watcher_log.txt`

**sync.py** is the core pipeline. For each run it:

- Validates column headers and aborts immediately if any are missing (guards against
  silent format changes from the data provider)
- Deduplicates by `client_id`, keeping the most recently updated record
- Cleans and normalizes each field (see data issues below)
- Upserts into `crm.db` inside a single transaction -- a mid-run crash rolls back
  completely, leaving no partial data
- Writes one row to `sync_runs` (run summary) and one row per issue to `sync_issues`
  (client ID, row number, original value, what was done)

---

## Data issues in the sample file

The sample CSV contained eight deliberate data quality problems. All are detected,
cleaned where possible, and logged with full detail in `sync_issues`.

| Issue | Assumption | Action taken |
|-------|-----------|-------------|
| Duplicate `client_id` (1002 appears twice) | Same client re-sent with an update | Kept record with most recent `last_updated`; discarded the earlier one |
| Missing phone (client 1003) | Value not provided; cannot be inferred | Stored `NULL`; logged for follow-up |
| Portfolio value `"2,100,000"` (commas) | Display formatting leaked into the feed | Commas stripped; stored as numeric `2100000` |
| Date `01/06/2026` (wrong format) | `DD/MM/YYYY` instead of `YYYY-MM-DD` | Parsed and normalized to `2026-06-01` |
| Invalid email `mateo.garcia@example` | Missing TLD; correct domain unknown | Stored as-is with `email_valid=0`; flagged for manual correction |
| Missing portfolio value (client 1007) | Value not provided; cannot be inferred | Stored `NULL`; logged for follow-up |
| Negative portfolio `-50,000` (client 1009) | Manual entry error -- all other values are 640k-2.1M; a negative portfolio has no valid business meaning | `portfolio_value` set to `NULL`; `portfolio_flagged=1`; original value preserved in `sync_issues` |
| Phone `+971501234568` (no spaces) | Valid UAE number, missing formatting | Normalized to `+971 50 123 4568`; original kept in `phone_raw` |

**On missing values:** fields like phone and portfolio that are simply absent are stored
as `NULL`. Inventing a value we do not have would be worse than leaving it blank --
it would introduce false data into the CRM with no way to distinguish it from a real value.

---

## Database schema

**clients** -- clean client records

| Column | Type | Notes |
|--------|------|-------|
| `client_id` | INTEGER PK | |
| `first_name`, `last_name` | TEXT NOT NULL | |
| `email` | TEXT | |
| `email_valid` | INTEGER | `0` if email failed format check |
| `phone_raw` | TEXT | Original value from source CSV |
| `phone` | TEXT | Normalized to `+971 XX XXX XXXX` |
| `portfolio_value` | REAL | `NULL` if missing or invalid |
| `portfolio_flagged` | INTEGER | `1` if negative or suspicious |
| `last_updated` | TEXT | `YYYY-MM-DD` |
| `data_issues` | TEXT | JSON array of issue objects for this record |
| `imported_at` | TEXT | Timestamp of first import |
| `updated_at` | TEXT | Timestamp of most recent update |

**sync_runs** -- one row per import run (source file, row counts, issue count, run timestamp)

**sync_issues** -- one row per issue (sync_run_id, client_id, row number, issue code, detail, resolution)

---

## Files

| File | Description |
|------|-------------|
| `app.py` | Streamlit web UI. Run: `streamlit run app.py` |
| `sync.py` | Core ETL script. Run directly: `python3 sync.py <csv_file>` |
| `watcher.py` | File watcher for automated mode. Run: `python3 watcher.py` |
| `generate_note.py` | Regenerates `note.pdf`. Run: `python3 generate_note.py` |
| `requirements.txt` | Python dependencies (`watchdog`, `fpdf2`, `streamlit`, `pandas`) |
| `note.pdf` | Half-page submission write-up (design, security, risks) |
| `sample_data/` | Sample CSV used for development and testing |
| `PLAN.md` | Planning document written before any code -- issues catalogued upfront |

Generated at runtime (not in repo):

| File / Folder | Description |
|---------------|-------------|
| `crm.db` | SQLite database |
| `sync_log.txt` | Log from most recent sync run |
| `watcher_log.txt` | Log from watcher process |
| `watch/` | Drop folder (created automatically by watcher.py) |
| `archive/` | Processed CSVs with timestamps (created automatically) |

---

## What I would add with more time

- **Exact column name validation** -- the current check catches missing columns but
  a renamed column with the same count would slip through. A strict name match would
  close this gap.
- **Email correction heuristics** -- for an address like `mateo.garcia@example`, a
  domain lookup could suggest likely completions rather than just flagging it.
- **Alerting on sync_issues patterns** -- if the same issue code appears across multiple
  consecutive runs, that is a signal the source data has a systemic problem. An alert
  (email or Slack) would surface it without waiting for a weekly manual review.
- **Config file** -- folder paths and validation rules are currently hardcoded. Moving
  them to a YAML config file would make the script reusable across different CRM feeds
  without touching code.
- **Tests** -- unit tests for each cleaning function and an integration test that runs
  the full pipeline against a fixture CSV and asserts the expected database state.
