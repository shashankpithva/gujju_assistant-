"""The sheet of people to call, and where their answers go: Google Sheets or a local CSV file."""

from __future__ import annotations

import os
from pathlib import Path

from agent.sheets.base import CALLING, FINAL_STATUSES, Contact, ContactSheet, SheetError
from agent.sheets.columns import ANSWER_KEYS, COLUMNS, KEYS
from agent.sheets.csv_sheet import CsvSheet
from agent.sheets.google_sheet import GoogleSheet, sheet_id_from

__all__ = [
    "ANSWER_KEYS",
    "CALLING",
    "COLUMNS",
    "FINAL_STATUSES",
    "KEYS",
    "Contact",
    "ContactSheet",
    "CsvSheet",
    "GoogleSheet",
    "SheetError",
    "open_sheet",
]


def open_sheet(ref: str | None = None) -> ContactSheet | None:
    """The sheet `ref` names ("google:<id>[#tab]" or "csv:<path>", as the dialer passes it to the
    agent), or else the one agent/.env names: GOOGLE_SHEET_ID first, then SURVEY_CSV. None if neither."""
    if ref:
        kind, _, where = ref.partition(":")
        if kind == "google":
            sheet_id, _, tab = where.partition("#")
            return GoogleSheet(sheet_id, tab or None)
        if kind == "csv":
            return CsvSheet(Path(where))
        raise SheetError(f"Unknown sheet {ref!r}: expected google:<id> or csv:<path>")
    if sheet_id := os.getenv("GOOGLE_SHEET_ID", "").strip():
        return GoogleSheet(sheet_id_from(sheet_id), os.getenv("GOOGLE_SHEET_TAB", "").strip() or None)
    if path := os.getenv("SURVEY_CSV", "").strip():
        return CsvSheet(Path(path))
    return None
