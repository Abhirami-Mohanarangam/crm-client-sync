#!/usr/bin/env python3
"""
generate_note.py -- Generates note.pdf for the submission.
Usage: python3 generate_note.py
Produces: note.pdf in the same directory.
"""

import os
from fpdf import FPDF, XPos, YPos

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "note.pdf")

NOTE_TITLE = "Technical Note: Automated CRM Client Sync"

SECTIONS = [
    {
        "heading": "How it works",
        "body": (
            "A Python script (sync.py) reads the incoming CSV, validates and cleans each row, "
            "and upserts records into a local SQLite database (crm.db) in one command. "
            "watcher.py monitors a drop folder and triggers the sync automatically whenever "
            "a new CSV file arrives, then archives the processed file with a timestamp.\n\n"
            "Eight data quality issues in the sample are detected and cleaned: duplicate "
            "client IDs (keep the most recently updated record), inconsistent date formats "
            "(normalize to YYYY-MM-DD), comma-formatted numbers (strip and parse as numeric), "
            "invalid email addresses (stored with email_valid=0 so they cannot be used "
            "downstream), missing phone numbers and portfolio values (stored as NULL), "
            "a negative portfolio value of -50,000 (NULLed out -- all other values in the "
            "file are between 640,000 and 2,100,000, so this is clearly a manual entry error; "
            "storing it would corrupt any average or sum calculation), and inconsistent UAE "
            "phone formatting (normalized to +971 XX XXX XXXX). Original bad values are "
            "preserved in sync_issues for audit. Every run also writes to sync_log.txt and "
            "a sync_runs table."
        ),
    },
    {
        "heading": "Keeping the data accurate and secure over time",
        "body": (
            "The script validates column headers before processing any rows and aborts if "
            "something is missing, so a provider format change does not silently corrupt the "
            "database. For recurring use I would schedule it via cron and review the "
            "sync_issues table weekly for patterns. For security, crm.db should have "
            "restricted file permissions, the incoming CSV should be archived after each "
            "import rather than left in a shared folder, and credentials should live in "
            "environment variables if this ever moves to a server."
        ),
    },
    {
        "heading": "What is most likely to go wrong",
        "body": (
            "A renamed column that still has the right field count would pass the header "
            "check and load incorrect data into the wrong column. The fix is matching exact "
            "column names rather than just checking for missing ones. The other risk is an "
            "interrupted run leaving the database in a partial state, but the entire import "
            "is already wrapped in a single transaction, so a mid-run crash rolls everything "
            "back cleanly."
        ),
    },
]


class NotePDF(FPDF):
    def header(self):
        pass

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def build_pdf():
    pdf = NotePDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_margins(22, 20, 22)

    # Title
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(31, 78, 121)
    pdf.cell(0, 8, NOTE_TITLE, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    # Thin rule
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.3)
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.w - 22, pdf.get_y())
    pdf.ln(5)

    for section in SECTIONS:
        # Section heading
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(50, 90, 140)
        pdf.cell(0, 6, section["heading"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1)

        # Body text
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(40, 40, 40)
        pdf.multi_cell(0, 5.2, section["body"])
        pdf.ln(4)

    pdf.output(OUTPUT_PATH)
    print(f"note.pdf written to {OUTPUT_PATH}")


if __name__ == "__main__":
    build_pdf()
