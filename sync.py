#!/usr/bin/env python3
"""
sync.py -- CRM Client Update Sync

Reads a client update CSV, validates and cleans every field, and upserts
records into a local SQLite database (crm.db).

Usage:
    python sync.py <path_to_csv>

Produces:
    crm.db       -- SQLite database with client records and full audit tables
    sync_log.txt -- Timestamped log of every action and issue found

On each run, the script:
  - Deduplicates by client_id (keeps the most recently updated record)
  - Normalizes date formats to YYYY-MM-DD
  - Strips comma formatting from portfolio values
  - Validates email addresses
  - Normalizes UAE phone numbers to +971 XX XXX XXXX
  - Flags missing or suspicious values
  - Upserts into crm.db (inserts new, updates existing if incoming is newer)
  - Records a full audit entry in sync_runs and sync_issues
"""

import csv
import sqlite3
import re
import logging
import sys
import os
import json
from datetime import datetime


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crm.db")
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync_log.txt")

EXPECTED_COLUMNS = {
    "client_id", "first_name", "last_name", "email",
    "phone", "portfolio_value", "last_updated"
}

UAE_MOBILE_PREFIXES = {"50", "52", "54", "55", "56", "58"}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging():
    logger = logging.getLogger("crm_sync")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS clients (
            client_id         INTEGER PRIMARY KEY,
            first_name        TEXT    NOT NULL,
            last_name         TEXT    NOT NULL,
            email             TEXT,
            email_valid       INTEGER NOT NULL DEFAULT 1,
            phone_raw         TEXT,
            phone             TEXT,
            portfolio_value   REAL,
            portfolio_flagged INTEGER NOT NULL DEFAULT 0,
            last_updated      TEXT,
            data_issues       TEXT,
            imported_at       TEXT    NOT NULL,
            updated_at        TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sync_runs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at        TEXT    NOT NULL,
            source_file   TEXT    NOT NULL,
            rows_read     INTEGER NOT NULL,
            rows_inserted INTEGER NOT NULL,
            rows_updated  INTEGER NOT NULL,
            rows_skipped  INTEGER NOT NULL,
            issues_found  INTEGER NOT NULL,
            summary       TEXT
        );

        CREATE TABLE IF NOT EXISTS sync_issues (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_run_id  INTEGER NOT NULL,
            client_id    TEXT,
            row_number   INTEGER,
            issue_code   TEXT    NOT NULL,
            issue_detail TEXT    NOT NULL,
            resolution   TEXT    NOT NULL,
            FOREIGN KEY (sync_run_id) REFERENCES sync_runs(id)
        );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Field validators and cleaners
# ---------------------------------------------------------------------------

def parse_date(raw, row_num, client_id, issues, logger):
    """
    Normalize last_updated to YYYY-MM-DD.
    Recognizes YYYY-MM-DD and DD/MM/YYYY. Logs any conversion.
    """
    if not raw or not raw.strip():
        return None

    value = raw.strip()

    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    except ValueError:
        pass

    try:
        d = datetime.strptime(value, "%d/%m/%Y")
        normalized = d.strftime("%Y-%m-%d")
        msg = (
            f"Row {row_num} | client_id={client_id} | DATE_FORMAT: "
            f"'{value}' is in DD/MM/YYYY format -- normalized to '{normalized}'"
        )
        logger.warning(msg)
        issues.append({
            "code": "DATE_FORMAT",
            "detail": f"last_updated was '{value}' (DD/MM/YYYY format)",
            "resolution": f"Normalized to '{normalized}' (YYYY-MM-DD)"
        })
        return normalized
    except ValueError:
        pass

    logger.error(
        f"Row {row_num} | client_id={client_id} | DATE_UNRECOGNIZED: "
        f"'{value}' could not be parsed as a date"
    )
    issues.append({
        "code": "DATE_UNRECOGNIZED",
        "detail": f"last_updated '{value}' is not a recognized date format",
        "resolution": "Stored as-is; manual review required"
    })
    return value


def validate_email(raw, row_num, client_id, issues, logger):
    """
    Validate email format. Requires local@domain.tld.
    Flags invalid addresses with email_valid=0 but does not reject the row.
    """
    if not raw or not raw.strip():
        return None, True

    value = raw.strip()
    pattern = r'^[^@\s]+@[^@\s]+\.[^@\s]+'

    if re.match(pattern, value):
        return value, True

    logger.warning(
        f"Row {row_num} | client_id={client_id} | INVALID_EMAIL: "
        f"'{value}' is missing a valid domain or TLD"
    )
    issues.append({
        "code": "INVALID_EMAIL",
        "detail": f"Email '{value}' failed format check (no valid TLD found)",
        "resolution": "Stored as-is with email_valid=0; manual correction required"
    })
    return value, False


def normalize_phone(raw, row_num, client_id, issues, logger):
    """
    Normalize UAE mobile numbers to '+971 XX XXX XXXX'.
    Stores both the original (phone_raw) and normalized (phone) values.
    Logs any transformation or missing value.
    """
    if not raw or not raw.strip():
        logger.warning(
            f"Row {row_num} | client_id={client_id} | MISSING_PHONE: "
            f"phone field is blank"
        )
        issues.append({
            "code": "MISSING_PHONE",
            "detail": "phone field is blank",
            "resolution": "Stored as NULL; requires follow-up to obtain phone number"
        })
        return None, None

    raw_value = raw.strip()
    stripped = re.sub(r'[\s\-]', '', raw_value)

    if not stripped.startswith('+971'):
        return raw_value, raw_value

    national = stripped[4:]

    if len(national) != 9:
        logger.warning(
            f"Row {row_num} | client_id={client_id} | PHONE_FORMAT: "
            f"'{raw_value}' has {len(national)} digits after +971 (expected 9)"
        )
        issues.append({
            "code": "PHONE_FORMAT",
            "detail": (
                f"'{raw_value}' has {len(national)} digits after +971 (expected 9). "
                f"Does not match UAE mobile format (+971 XX XXX XXXX)"
            ),
            "resolution": "Stored as-is; manual verification required"
        })
        return raw_value, raw_value

    prefix     = national[:2]
    subscriber = national[2:]
    normalized = f"+971 {prefix} {subscriber[:3]} {subscriber[3:]}"

    if normalized != raw_value:
        logger.info(
            f"Row {row_num} | client_id={client_id} | PHONE_FORMAT: "
            f"'{raw_value}' normalized to '{normalized}'"
        )
        issues.append({
            "code": "PHONE_FORMAT",
            "detail": f"Phone '{raw_value}' was not in standard format (+971 XX XXX XXXX)",
            "resolution": f"Normalized to '{normalized}'; original stored in phone_raw"
        })

    return raw_value, normalized


def parse_portfolio(raw, row_num, client_id, all_values_context, issues, logger):
    """
    Parse portfolio_value: strip commas, convert to float.
    Missing values are stored as NULL.
    Negative values are treated as invalid data (clearly a manual entry error) --
    the bad value is NULLed out in portfolio_value so it cannot corrupt downstream
    calculations or reports. The original raw value is preserved in the issue log.
    Uses all_values_context to provide range context in the log message.
    """
    if not raw or not raw.strip():
        logger.warning(
            f"Row {row_num} | client_id={client_id} | MISSING_PORTFOLIO: "
            f"portfolio_value is blank"
        )
        issues.append({
            "code": "MISSING_PORTFOLIO",
            "detail": "portfolio_value field is blank",
            "resolution": "Stored as NULL; requires follow-up to obtain correct value"
        })
        return None, False

    cleaned = raw.strip().replace(',', '')

    if cleaned != raw.strip():
        logger.info(
            f"Row {row_num} | client_id={client_id} | PORTFOLIO_FORMAT: "
            f"'{raw.strip()}' contained comma formatting -- parsed as {cleaned}"
        )
        issues.append({
            "code": "PORTFOLIO_FORMAT",
            "detail": f"portfolio_value '{raw.strip()}' contained comma number formatting",
            "resolution": f"Commas stripped; stored as numeric {cleaned}"
        })

    try:
        amount = float(cleaned)
    except ValueError:
        logger.error(
            f"Row {row_num} | client_id={client_id} | PORTFOLIO_PARSE_ERROR: "
            f"'{raw.strip()}' cannot be parsed as a number"
        )
        issues.append({
            "code": "PORTFOLIO_PARSE_ERROR",
            "detail": f"portfolio_value '{raw.strip()}' is not a valid number",
            "resolution": "Stored as NULL; manual correction required"
        })
        return None, False

    if amount < 0:
        other_vals = [v for v in all_values_context if v is not None and v >= 0]
        if other_vals:
            range_min = int(min(other_vals))
            range_max = int(max(other_vals))
            range_note = (
                f"All other portfolio values in this file range from "
                f"{range_min:,} to {range_max:,}."
            )
        else:
            range_note = "No other positive values in file for comparison."

        logger.warning(
            f"Row {row_num} | client_id={client_id} | NEGATIVE_PORTFOLIO: "
            f"Raw value was {amount:,.0f}. {range_note} "
            f"Treating as a manual entry error (sign flip or wrong field). "
            f"Nulled out in portfolio_value to prevent downstream data corruption. "
            f"Original value preserved in sync_issues."
        )
        issues.append({
            "code": "NEGATIVE_PORTFOLIO",
            "detail": (
                f"portfolio_value was {amount:,.0f}. {range_note} "
                f"A negative portfolio value is not a valid business value -- "
                f"almost certainly a manual entry error."
            ),
            "resolution": (
                f"portfolio_value set to NULL and portfolio_flagged=1. "
                f"Original raw value ({amount:,.0f}) preserved here for audit. "
                f"Correct value must be obtained and updated manually."
            )
        })
        return None, True

    return amount, False


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def deduplicate(rows, issues_log, logger):
    """
    Group rows by client_id. Where duplicates exist, keep the row with the
    most recent last_updated date. Logs each duplicate pair found.
    Returns (unique_rows, duplicate_count).
    """
    seen      = {}
    dup_count = 0

    for row in rows:
        cid = row['client_id']

        if cid not in seen:
            seen[cid] = row
            continue

        existing      = seen[cid]
        existing_date = existing['last_updated'] or ''
        incoming_date = row['last_updated'] or ''

        if incoming_date > existing_date:
            discarded = existing
            kept      = row
        else:
            discarded = row
            kept      = existing

        dup_count += 1
        logger.warning(
            f"Row {row['row_num']} | client_id={cid} | DUPLICATE_ROW: "
            f"client_id={cid} appears more than once. "
            f"Keeping record with last_updated={kept['last_updated']}, "
            f"discarding record with last_updated={discarded['last_updated']}."
        )
        issues_log.append((
            cid,
            discarded['row_num'],
            {
                "code": "DUPLICATE_ROW",
                "detail": (
                    f"client_id={cid} appears more than once in the source file. "
                    f"This row has last_updated={discarded['last_updated']}; "
                    f"another row has last_updated={kept['last_updated']}."
                ),
                "resolution": (
                    f"This row was discarded. The row with "
                    f"last_updated={kept['last_updated']} was kept (most recent)."
                )
            }
        ))
        seen[cid] = kept

    return list(seen.values()), dup_count


# ---------------------------------------------------------------------------
# Main sync
# ---------------------------------------------------------------------------

def run_sync(csv_path, logger, db_path=None):
    if db_path is None:
        db_path = DB_PATH

    run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("=" * 68)
    logger.info(f"SYNC START | source={os.path.basename(csv_path)} | run_at={run_at}")
    logger.info("=" * 68)

    # --- Read CSV -----------------------------------------------------------
    try:
        with open(csv_path, newline='', encoding='utf-8') as f:
            reader   = csv.DictReader(f)
            columns  = set(reader.fieldnames or [])
            raw_rows = [dict(r) for r in reader]
    except FileNotFoundError:
        logger.error(f"File not found: {csv_path}")
        raise RuntimeError(f"File not found: {csv_path}")

    missing_cols = EXPECTED_COLUMNS - columns
    if missing_cols:
        msg = (
            f"CSV is missing expected column(s): {', '.join(sorted(missing_cols))}. "
            f"Aborting -- the file format may have changed."
        )
        logger.error(msg)
        raise RuntimeError(msg)

    rows_read = len(raw_rows)
    logger.info(f"Read {rows_read} data rows from CSV")

    # --- First pass: parse dates (needed for deduplication) -----------------
    pre_rows   = []
    dup_issues = []

    for row_num, row in enumerate(raw_rows, start=2):
        cid  = row.get('client_id', '').strip()
        temp = []
        last_updated = parse_date(
            row.get('last_updated', ''), row_num, cid, temp, logger
        )
        pre_rows.append({
            'client_id':   cid,
            'last_updated': last_updated,
            'raw':          row,
            'row_num':      row_num,
            'date_issues':  temp,
        })

    # --- Deduplicate --------------------------------------------------------
    unique_rows, dup_count = deduplicate(pre_rows, dup_issues, logger)
    logger.info(
        f"Deduplication complete: {len(unique_rows)} unique record(s), "
        f"{dup_count} duplicate(s) discarded"
    )

    # --- Collect portfolio values for range context -------------------------
    raw_portfolio_vals = []
    for r in unique_rows:
        raw = r['raw'].get('portfolio_value', '').strip().replace(',', '')
        try:
            raw_portfolio_vals.append(float(raw))
        except ValueError:
            pass

    # --- Second pass: full validation and cleaning --------------------------
    cleaned_rows  = []
    all_row_issues = list(dup_issues)  # includes duplicate issues

    for r in unique_rows:
        row_num  = r['row_num']
        cid      = r['client_id']
        row      = r['raw']
        issues   = list(r['date_issues'])

        email, email_valid = validate_email(
            row.get('email', ''), row_num, cid, issues, logger
        )
        phone_raw, phone = normalize_phone(
            row.get('phone', ''), row_num, cid, issues, logger
        )
        portfolio_value, portfolio_flagged = parse_portfolio(
            row.get('portfolio_value', ''), row_num, cid,
            raw_portfolio_vals, issues, logger
        )

        if issues:
            for issue in issues:
                all_row_issues.append((cid, row_num, issue))

        cleaned_rows.append({
            'client_id':        int(cid),
            'first_name':       row.get('first_name', '').strip(),
            'last_name':        row.get('last_name', '').strip(),
            'email':            email,
            'email_valid':      1 if email_valid else 0,
            'phone_raw':        phone_raw,
            'phone':            phone,
            'portfolio_value':  portfolio_value,
            'portfolio_flagged': 1 if portfolio_flagged else 0,
            'last_updated':     r['last_updated'],
            'data_issues':      json.dumps(issues) if issues else None,
        })

    # --- Upsert into SQLite -------------------------------------------------
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)

    rows_inserted = 0
    rows_updated  = 0
    rows_skipped  = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        for row in cleaned_rows:
            existing = conn.execute(
                "SELECT client_id, last_updated FROM clients WHERE client_id = ?",
                (row['client_id'],)
            ).fetchone()

            if existing is None:
                conn.execute("""
                    INSERT INTO clients
                        (client_id, first_name, last_name, email, email_valid,
                         phone_raw, phone, portfolio_value, portfolio_flagged,
                         last_updated, data_issues, imported_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row['client_id'], row['first_name'], row['last_name'],
                    row['email'], row['email_valid'],
                    row['phone_raw'], row['phone'],
                    row['portfolio_value'], row['portfolio_flagged'],
                    row['last_updated'], row['data_issues'],
                    now, now
                ))
                rows_inserted += 1
                logger.info(
                    f"INSERTED client_id={row['client_id']} "
                    f"({row['first_name']} {row['last_name']})"
                )

            else:
                db_date  = existing['last_updated'] or ''
                src_date = row['last_updated'] or ''

                if src_date > db_date:
                    conn.execute("""
                        UPDATE clients SET
                            first_name=?, last_name=?, email=?, email_valid=?,
                            phone_raw=?, phone=?, portfolio_value=?,
                            portfolio_flagged=?, last_updated=?,
                            data_issues=?, updated_at=?
                        WHERE client_id=?
                    """, (
                        row['first_name'], row['last_name'],
                        row['email'], row['email_valid'],
                        row['phone_raw'], row['phone'],
                        row['portfolio_value'], row['portfolio_flagged'],
                        row['last_updated'], row['data_issues'],
                        now, row['client_id']
                    ))
                    rows_updated += 1
                    logger.info(
                        f"UPDATED  client_id={row['client_id']} "
                        f"({row['first_name']} {row['last_name']}) "
                        f"| last_updated: {db_date} -> {src_date}"
                    )

                else:
                    rows_skipped += 1
                    logger.info(
                        f"SKIPPED  client_id={row['client_id']} "
                        f"({row['first_name']} {row['last_name']}) "
                        f"| DB already has equal or newer record ({db_date})"
                    )

        # --- Record sync run and issues -------------------------------------
        issues_found = len(all_row_issues)
        summary_lines = [
            f"Source file  : {os.path.basename(csv_path)}",
            f"Rows read    : {rows_read}",
            f"After dedup  : {len(unique_rows)}",
            f"Inserted     : {rows_inserted}",
            f"Updated      : {rows_updated}",
            f"Skipped      : {rows_skipped}",
            f"Issues found : {issues_found}",
        ]
        summary = "\n".join(summary_lines)

        cursor = conn.execute("""
            INSERT INTO sync_runs
                (run_at, source_file, rows_read, rows_inserted, rows_updated,
                 rows_skipped, issues_found, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_at, os.path.basename(csv_path), rows_read,
            rows_inserted, rows_updated, rows_skipped, issues_found, summary
        ))
        sync_run_id = cursor.lastrowid

        for (cid, row_num, issue) in all_row_issues:
            conn.execute("""
                INSERT INTO sync_issues
                    (sync_run_id, client_id, row_number,
                     issue_code, issue_detail, resolution)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                sync_run_id, cid, row_num,
                issue['code'], issue['detail'], issue['resolution']
            ))

        conn.commit()

    except Exception as exc:
        conn.rollback()
        logger.error(f"Database error -- transaction rolled back: {exc}")
        raise
    finally:
        conn.close()

    # --- Final summary ------------------------------------------------------
    logger.info("")
    logger.info("=" * 68)
    logger.info("SYNC COMPLETE")
    for line in summary_lines:
        logger.info(line)
    logger.info(f"Database    : {db_path}")
    logger.info(f"Log file    : {LOG_PATH}")
    logger.info("=" * 68)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python sync.py <path_to_csv>")
        sys.exit(1)

    log = setup_logging()
    try:
        run_sync(sys.argv[1], log)
    except RuntimeError:
        sys.exit(1)
