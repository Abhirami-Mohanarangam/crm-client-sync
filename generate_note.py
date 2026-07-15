#!/usr/bin/env python3
"""
generate_note.py -- Generates note.pdf for the submission.
Usage: python3 generate_note.py
"""

import os
from fpdf import FPDF, XPos, YPos

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "note.pdf")
FONT_DIR    = "/System/Library/Fonts/Supplemental"

BLUE_DARK = (31, 78, 121)
BLUE_MID  = (46, 116, 181)
BODY_COL  = (40, 40, 40)
RULE_COL  = (190, 210, 230)


class NotePDF(FPDF):
    def header(self):
        pass
    def footer(self):
        self.set_y(-12)
        self.set_font("Ar", "I", 8)
        self.set_text_color(160, 160, 160)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def add_fonts(pdf):
    pdf.add_font("Ar",  "",   f"{FONT_DIR}/Arial.ttf")
    pdf.add_font("Ar",  "B",  f"{FONT_DIR}/Arial Bold.ttf")
    pdf.add_font("Ar",  "I",  f"{FONT_DIR}/Arial Italic.ttf")


def rule(pdf, before=1, after=3):
    pdf.ln(before)
    pdf.set_draw_color(*RULE_COL)
    pdf.set_line_width(0.25)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(after)


def section(pdf, title):
    pdf.ln(3.5)
    pdf.set_font("Ar", "B", 9.5)
    pdf.set_text_color(*BLUE_MID)
    pdf.cell(0, 5.5, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(0.5)


def para(pdf, text, lh=4.9):
    pdf.set_font("Ar", "", 9)
    pdf.set_text_color(*BODY_COL)
    pdf.multi_cell(0, lh, text)


def bul(pdf, text, lh=4.8, indent=4.5, desc_indent=8.5):
    """
    Bullet point. Use pipe | to split a bold label from a plain description.
    Label appears on its own line with bullet. Description is indented below.
    Without a pipe, just a plain bullet with wrapped text.
    """
    w = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.set_text_color(*BODY_COL)

    if "|" in text:
        label, rest = text.split("|", 1)
        # Line 1: dash + bold label
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Ar", "", 9)
        pdf.cell(indent, lh, "-")
        pdf.set_font("Ar", "B", 9)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(w - indent, lh, label.strip(),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        # Line 2+: plain description, indented
        pdf.set_font("Ar", "", 9)
        pdf.set_x(pdf.l_margin + desc_indent)
        pdf.multi_cell(w - desc_indent, lh, rest.strip(),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    else:
        pdf.set_font("Ar", "", 9)
        pdf.set_x(pdf.l_margin)
        pdf.cell(indent, lh, "-")
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(w - indent, lh, text.strip(),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(0.8)


def build_pdf():
    pdf = NotePDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_margins(22, 18, 22)
    add_fonts(pdf)

    # Title
    pdf.set_font("Ar", "B", 14)
    pdf.set_text_color(*BLUE_DARK)
    pdf.cell(0, 9, "Technical Note: Automated CRM Client Sync",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    rule(pdf, before=1, after=4)

    # ---- What it is -------------------------------------------------------
    section(pdf, "What it is")
    para(pdf,
         "A Python pipeline that reads a daily client update CSV, validates and "
         "cleans the data, and upserts records into a local SQLite database (crm.db). "
         "A file watcher (watcher.py) triggers the sync automatically the moment a "
         "new CSV lands in the watch/ folder -- no manual steps, no scheduled polling.")

    # ---- How it works -----------------------------------------------------
    section(pdf, "How it works")
    bul(pdf, "Drop a CSV into watch/. The watcher detects it, runs sync.py, and "
             "moves the file to archive/ with a timestamp.")
    bul(pdf, "sync.py validates column headers first (aborts if any are missing), "
             "deduplicates by client_id, cleans each field, then upserts everything "
             "in a single transaction. A mid-run crash rolls back completely.")
    bul(pdf, "Three tables: clients (clean data only), sync_runs (one audit row per "
             "run), sync_issues (one row per issue -- client ID, row number, original "
             "value, resolution). Business queries never touch dirty data.")

    # ---- Data cleaning ----------------------------------------------------
    section(pdf, "Data cleaning -- issues found and how each was handled")

    bul(pdf, "Duplicate client_id (1002 appears twice)| "
             "Same client re-sent with an update. Kept the row with the most recent "
             "last_updated; discarded the earlier one.")

    bul(pdf, "Missing phone (1003)| "
             "No value provided. We cannot invent a phone number we do not have. "
             "Stored NULL; logged for follow-up.")

    bul(pdf, "Comma-formatted number (1004: \"2,100,000\")| "
             "Display formatting that leaked into the feed. Stripped commas; stored as "
             "numeric 2100000.")

    bul(pdf, "Wrong date format (1005: 01/06/2026)| "
             "DD/MM/YYYY instead of YYYY-MM-DD. Parsed and normalized to 2026-06-01.")

    bul(pdf, "Invalid email (1006: mateo.garcia@example)| "
             "Missing TLD. We cannot guess the correct domain. Stored as-is with "
             "email_valid=0; flagged for manual correction.")

    bul(pdf, "Missing portfolio value (1007)| "
             "No value provided. We cannot invent a portfolio figure. Stored NULL; "
             "logged for follow-up.")

    bul(pdf, "Negative portfolio value (1009: -50,000)| "
             "All other values are 640,000-2,100,000. A negative portfolio has no "
             "valid business meaning -- storing it would corrupt any average or total. "
             "NULLed out; original value preserved in sync_issues for audit.")

    bul(pdf, "Inconsistent phone format (1002: +971501234568)| "
             "Valid UAE number, missing spaces. Normalized to +971 50 123 4568; "
             "original kept in phone_raw.")

    # ---- Accuracy and security --------------------------------------------
    section(pdf, "Accuracy and security over time")
    bul(pdf, "Review sync_issues weekly -- recurring patterns surface provider-side "
             "problems before they compound.")
    bul(pdf, "Restrict crm.db file permissions. Archive incoming CSVs after import; "
             "do not leave them in shared folders.")
    bul(pdf, "If this moves to a server: credentials in environment variables, "
             "database connections over TLS.")

    # ---- Risks ------------------------------------------------------------
    section(pdf, "What is most likely to go wrong")
    para(pdf,
         "A column renamed by the provider but still present passes the header check "
         "and loads data into the wrong field silently. The fix is exact name matching "
         "rather than just presence checking. Everything else -- crashes, invalid values, "
         "duplicates -- is already handled.")

    pdf.output(OUTPUT_PATH)
    print(f"note.pdf written to {OUTPUT_PATH}")


if __name__ == "__main__":
    build_pdf()
