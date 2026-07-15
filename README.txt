Submission: Automated CRM Client Sync
======================================

Files
-----
sync.py           Main script. Reads the CSV, cleans the data, and loads
                  records into crm.db. Run with: python3 sync.py <path_to_csv>

crm.db            SQLite database produced by running sync.py. Contains three
                  tables: clients (the cleaned records), sync_runs (one row per
                  import run), and sync_issues (one row per data issue found).
                  Open with DB Browser for SQLite (free at sqlitebrowser.org)
                  or any SQLite client.

sync_log.txt      Plain-text log from the sync run. Every issue found, every
                  record inserted or updated, and a summary at the end.

note.pdf          Half-page write-up covering how the solution works, how to
                  keep the data accurate and secure over time, and what is most
                  likely to go wrong.

generate_note.py  Script used to produce note.pdf. Requires fpdf2:
                  pip3 install fpdf2

PLAN.md           Planning document written before coding started. Covers the
                  full list of data issues found, the resolution for each, and
                  the database schema.


How to run
----------
1. Install fpdf2 if not already present:
      pip3 install fpdf2

2. Run the sync:
      python3 sync.py /path/to/client_updates_sample_round_1_interview.csv

3. Check the output:
      - crm.db      (open in DB Browser for SQLite)
      - sync_log.txt (open in any text editor)

No other dependencies. Python 3.6+ and the standard library are all that
sync.py needs. fpdf2 is only required to regenerate note.pdf.
