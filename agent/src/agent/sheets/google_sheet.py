"""A contact sheet in Google Sheets: the one to use for a demo, as the answers appear while people talk.

Access is through a Google Cloud service account (a robot Google account with a key file). Share the
sheet with the service account's email address as an Editor, the way you'd share it with a person.
docs/agent.md walks through creating one.
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

from agent.sheets.base import Cell, SheetError, TableSheet

# Sheets only: the sheet is opened by its id, so the service account needs no access to Drive.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_ID_IN_URL = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")


def sheet_id_from(text: str) -> str:
    """The sheet's id, from the id itself or the sheet's whole address."""
    match = _ID_IN_URL.search(text)
    return match.group(1) if match else text.strip()


def service_account_info() -> dict[str, Any]:
    """The service account key: GOOGLE_SERVICE_ACCOUNT_JSON (the key itself, or base64 of it, for
    places that only take secrets as text, like LiveKit Cloud), or GOOGLE_SERVICE_ACCOUNT_FILE."""
    inline = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    try:
        if inline:
            text = inline if inline.startswith("{") else base64.b64decode(inline).decode("utf-8")
            return json.loads(text)
        if path:
            return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        raise SheetError(f"The Google service account key couldn't be read: {e}") from e
    raise SheetError(
        "Set GOOGLE_SERVICE_ACCOUNT_FILE to a service account key file (or GOOGLE_SERVICE_ACCOUNT_JSON to "
        "its contents) in agent/.env, to use a Google Sheet."
    )


class GoogleSheet(TableSheet):
    def __init__(
        self, sheet_id: str, tab: str | None = None, *, credentials: dict[str, Any] | None = None
    ) -> None:
        super().__init__()
        self._id = sheet_id_from(sheet_id)
        self._tab = tab or None
        self._credentials = credentials
        self._worksheet_handle: Any = None
        self._account = ""

    @property
    def ref(self) -> str:
        return f"google:{self._id}" + (f"#{self._tab}" if self._tab else "")

    @property
    def label(self) -> str:
        return f"Google Sheet {self._id[:10]}…" + (f" (tab {self._tab})" if self._tab else "")

    @property
    def url(self) -> str:
        return f"https://docs.google.com/spreadsheets/d/{self._id}/edit"

    def _worksheet(self) -> Any:
        if self._worksheet_handle is not None:
            return self._worksheet_handle
        import gspread

        info = self._credentials or service_account_info()
        self._account = str(info.get("client_email", "the service account"))
        try:
            # BackOffHTTPClient waits and retries when Google says "too many requests".
            client = gspread.service_account_from_dict(
                info, scopes=SCOPES, http_client=gspread.BackOffHTTPClient
            )
            book = client.open_by_key(self._id)
            self._worksheet_handle = book.worksheet(self._tab) if self._tab else book.sheet1
        except gspread.exceptions.WorksheetNotFound as e:
            raise SheetError(
                f"The Google Sheet has no tab named {self._tab!r}: check GOOGLE_SHEET_TAB."
            ) from e
        except (gspread.exceptions.SpreadsheetNotFound, gspread.exceptions.APIError) as e:
            raise SheetError(self._cant_open(e)) from e
        return self._worksheet_handle

    def _cant_open(self, error: Exception) -> str:
        return (
            f"Can't open the Google Sheet {self._id}: share it with {self._account} as an Editor, and check "
            f"GOOGLE_SHEET_ID. ({error})"
        )

    def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        import gspread

        try:
            return fn(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            raise SheetError(self._cant_open(e)) from e

    def _read_all(self) -> list[list[str]]:
        return self._call(self._worksheet().get_all_values)

    def _read_top(self, rows: int) -> list[list[str]]:
        return self._call(self._worksheet().get_values, f"1:{rows}")

    def _write_cells(self, cells: list[tuple[int, int, Cell]]) -> None:
        from gspread.utils import ValueInputOption, rowcol_to_a1

        sheet = self._worksheet()
        rows, cols = max(r for r, _, _ in cells), max(c for _, c, _ in cells)
        if cols > sheet.col_count:
            self._call(sheet.add_cols, cols - sheet.col_count)
        if rows > sheet.row_count:
            self._call(sheet.add_rows, rows - sheet.row_count)
        # RAW: "+919876543210" stays text, never a formula or a number with its + lost. The number
        # columns come as ints and floats, and RAW keeps those numbers.
        data = [{"range": rowcol_to_a1(r, c), "values": [[v]]} for r, c, v in cells]
        self._call(sheet.batch_update, data, value_input_option=ValueInputOption.raw)

    def _insert_header(self, header: list[str]) -> None:
        from gspread.utils import ValueInputOption

        self._call(self._worksheet().insert_row, header, index=1, value_input_option=ValueInputOption.raw)

    def _append_row(self, values: list[Cell]) -> int:
        from gspread.utils import ValueInputOption

        result = self._call(
            self._worksheet().append_row, values, value_input_option=ValueInputOption.raw, table_range="A1"
        )
        updated = (result or {}).get("updates", {}).get("updatedRange", "")  # "Sheet1!A7:N7"
        match = re.search(r"![A-Z]+(\d+)", updated)
        if not match:
            raise SheetError(f"Google didn't say where the new row went ({updated!r})")
        return int(match.group(1))

    def _write_tab(self, title: str, rows: list[list[Cell]]) -> str:
        """A tab in the same spreadsheet, added at the end so the contacts stay the first tab. Run
        again, it's cleared and rewritten in place, so charts drawn on it keep working."""
        import gspread
        from gspread.utils import ValueInputOption

        book = self._worksheet().spreadsheet
        width = max((len(row) for row in rows), default=1)
        try:
            tab = book.worksheet(title)
            self._call(tab.clear)
            if tab.row_count < len(rows) or tab.col_count < width:
                self._call(tab.resize, max(tab.row_count, len(rows)), max(tab.col_count, width))
        except gspread.exceptions.WorksheetNotFound:
            tab = self._call(book.add_worksheet, title, rows=len(rows) + 20, cols=max(width, 8))
        table = [list(row) + [""] * (width - len(row)) for row in rows]
        self._call(tab.update, table, "A1", value_input_option=ValueInputOption.raw)
        return f"{self.url}#gid={tab.id}"
