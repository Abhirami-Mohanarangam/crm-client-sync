#!/usr/bin/env python3
"""
app.py -- Streamlit web interface for the CRM Client Sync pipeline.

Upload a CSV file to see the cleaned client data and any data quality
issues found during processing. Each upload runs an isolated pipeline
against a temporary database, so nothing persists between sessions.

Usage:
    streamlit run app.py
"""

import io
import logging
import os
import sqlite3
import tempfile

import pandas as pd
import streamlit as st

import sync as _sync


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _list_handler():
    """Return a (logger, records_list) pair that captures log output."""
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    logger = logging.getLogger(f"crm_app_{id(records)}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    handler = _Capture()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    return logger, records


def run_pipeline(csv_bytes: bytes, filename: str):
    """
    Write csv_bytes to a temp file, run the sync pipeline against a
    temp SQLite database, and return DataFrames for display.

    Returns:
        clients_df   -- cleaned client records
        issues_df    -- data quality issues found
        run_row      -- dict with the sync_runs summary row
        log_lines    -- list of log strings
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, filename)
        db_path  = os.path.join(tmpdir, "crm.db")

        with open(csv_path, "wb") as fh:
            fh.write(csv_bytes)

        logger, log_lines = _list_handler()

        _sync.run_sync(csv_path, logger, db_path=db_path)

        conn = sqlite3.connect(db_path)

        clients_df = pd.read_sql_query(
            "SELECT * FROM clients ORDER BY client_id", conn
        )
        issues_df = pd.read_sql_query(
            """
            SELECT si.client_id, si.row_number, si.issue_code,
                   si.issue_detail, si.resolution
            FROM   sync_issues si
            JOIN   sync_runs sr ON si.sync_run_id = sr.id
            ORDER  BY si.id
            """,
            conn,
        )
        run_row = pd.read_sql_query(
            "SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1", conn
        ).iloc[0].to_dict()

        conn.close()

    return clients_df, issues_df, run_row, log_lines


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="CRM Client Sync",
    page_icon="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'/>",
    layout="wide",
)

st.title("CRM Client Sync")
st.markdown(
    "Upload a client update CSV to validate, clean, and preview the records. "
    "Only `.csv` files are accepted."
)

uploaded = st.file_uploader("Choose a CSV file", type=["csv"], label_visibility="collapsed")

if uploaded is None:
    st.info("Upload a CSV file above to get started. "
            "You can use `sample_data/client_updates_sample.csv` from the repo to test.")
    st.stop()

# Verify it really is text/csv or has a .csv extension (file_uploader already
# filters by extension; this check guards against renamed files).
raw_bytes = uploaded.read()
try:
    raw_bytes.decode("utf-8")
except UnicodeDecodeError:
    st.error("The file could not be read as UTF-8 text. Please upload a valid CSV.")
    st.stop()

with st.spinner("Running pipeline..."):
    try:
        clients_df, issues_df, run_row, log_lines = run_pipeline(
            raw_bytes, uploaded.name
        )
    except RuntimeError as exc:
        st.error(f"Pipeline failed: {exc}")
        st.stop()

# ---------------------------------------------------------------------------
# Run summary
# ---------------------------------------------------------------------------

st.subheader("Run summary")

cols = st.columns(5)
cols[0].metric("Rows read",    run_row["rows_read"])
cols[1].metric("Inserted",     run_row["rows_inserted"])
cols[2].metric("Updated",      run_row["rows_updated"])
cols[3].metric("Skipped",      run_row["rows_skipped"])
cols[4].metric("Issues found", run_row["issues_found"])

# ---------------------------------------------------------------------------
# Clients table
# ---------------------------------------------------------------------------

st.subheader("Cleaned client records")

display_cols = [
    "client_id", "first_name", "last_name",
    "email", "email_valid",
    "phone", "portfolio_value", "portfolio_flagged",
    "last_updated",
]
display_df = clients_df[[c for c in display_cols if c in clients_df.columns]]

st.dataframe(display_df, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Data quality issues
# ---------------------------------------------------------------------------

st.subheader("Data quality issues")

if issues_df.empty:
    st.success("No issues found.")
else:
    st.dataframe(issues_df, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Pipeline log (collapsed by default)
# ---------------------------------------------------------------------------

with st.expander("Pipeline log"):
    st.code("\n".join(log_lines), language=None)
