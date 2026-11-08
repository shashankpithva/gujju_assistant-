"""A contact sheet: rows of phone numbers in, survey answers out, whichever backend holds it.

The backends (Google Sheets, a CSV file) only read and write cells. Everything else is here, once:
finding the header, adding missing columns, and turning rows into contacts. Every operation runs in
a worker thread, because a voice call's event loop must never wait on a disk or the network: a
blocked loop is heard as the voice breaking up.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Protocol

from agent.phone import normalize_phone
from agent.sheets.columns import ANSWER_KEYS, HEADER_SEARCH_ROWS, Layout, complete, find_layout, new_header

logger = logging.getLogger("agent.sheets")

# Statuses the agent and the dialer write. A row with none is waiting for its first call.
CALLING = "calling"
FINAL_STATUSES = ("completed", "partial", "busy", "no_answer", "declined", "failed")


class SheetError(Exception):
    """The sheet can't be used as it is; the message says what to change."""


@dataclass(frozen=True)
class Contact:
    row: int  # 1-based, as the sheet numbers it
    phone: str  # as written in the sheet
    values: Mapping[str, str]

    @property
    def status(self) -> str:
        return self.values.get("status", "").strip().lower()

    @property
    def attempts(self) -> int:
        try:
            return int(float(self.values.get("attempts", "") or 0))
        except ValueError:
            return 0

    @property
    def answered(self) -> bool:
        return any(self.values.get(key, "").strip() for key in ANSWER_KEYS)


class ContactSheet(Protocol):
    @property
    def ref(self) -> str:
        """How the dialer tells the agent which sheet a call belongs to: see sheets.open_sheet."""
        ...

    @property
    def label(self) -> str:
        """For people: "Google Sheet 1AbC…" or "contacts.csv"."""
        ...

    async def contacts(self) -> list[Contact]: ...

    async def update(self, row: int, values: Mapping[str, str]) -> None: ...

    async def append(self, values: Mapping[str, str]) -> int: ...


class TableSheet:
    """A sheet as a table of strings. Backends provide the blocking methods at the bottom."""

    def __init__(self) -> None:
        self._layout: Layout | None = None
        self._lock = asyncio.Lock()  # one operation at a time from this process

    async def contacts(self) -> list[Contact]:
        """Every row with a phone number, after making sure the header has every column."""
        async with self._lock:
            return await asyncio.to_thread(self._contacts)

    async def update(self, row: int, values: Mapping[str, str]) -> None:
        async with self._lock:
            await asyncio.to_thread(self._update, row, dict(values))

    async def append(self, values: Mapping[str, str]) -> int:
        async with self._lock:
            return await asyncio.to_thread(self._append_values, dict(values))

    # Blocking, in a worker thread ---------------------------------------------------------------

    def _contacts(self) -> list[Contact]:
        with self._exclusive():
            rows = self._read_all()
            layout, changed = self._settle_layout(rows)
            if changed:
                rows = self._read_all()
        phone_at = layout.columns["phone"] - 1
        contacts = []
        for number, row in enumerate(rows[layout.header_row :], start=layout.header_row + 1):
            phone = row[phone_at].strip() if phone_at < len(row) else ""
            if phone:
                values = {key: _cell(row, col) for key, col in layout.columns.items()}
                contacts.append(Contact(number, phone, values))
        return contacts

    def _update(self, row: int, values: dict[str, str]) -> None:
        with self._exclusive():
            layout = self._known_layout()
            cells = [
                (row, layout.columns[key], value) for key, value in values.items() if key in layout.columns
            ]
            if cells:
                self._write_cells(cells)

    def _append_values(self, values: dict[str, str]) -> int:
        with self._exclusive():
            layout = self._known_layout()
            row = [""] * layout.width
            for key, value in values.items():
                if key in layout.columns:
                    row[layout.columns[key] - 1] = value
            return self._append_row(row)

    def _known_layout(self) -> Layout:
        if self._layout is None:
            self._layout, _ = self._settle_layout(self._read_top(HEADER_SEARCH_ROWS))
        return self._layout

    def _settle_layout(self, rows: list[list[str]]) -> tuple[Layout, bool]:
        """Find the header, or make one, and add the columns it lacks. Returns the layout and
        whether the sheet was changed. The layout is kept for later writes."""
        changed = False
        layout = find_layout(rows)
        if layout is None:
            if not any(cell.strip() for row in rows for cell in row):
                self._write_cells([(1, col, header) for col, header in enumerate(new_header(), start=1)])
            elif _numbers_without_header(rows):
                self._insert_header(new_header())
            else:
                raise SheetError(
                    "No phone column found. Put the numbers in a column headed 'Phone' (or 'ફોન નંબર') "
                    "in one of the top rows."
                )
            layout = find_layout([new_header()])
            assert layout is not None
            changed = True
        if added := complete(layout):
            self._write_cells([(layout.header_row, col, header) for col, header in added])
            logger.info("added columns to the sheet: %s", ", ".join(header for _, header in added))
            changed = True
        self._layout = layout
        return layout, changed

    @contextlib.contextmanager
    def _exclusive(self) -> Iterator[None]:
        """A lock shared with other processes, for a backend that needs one (a file)."""
        yield

    def _read_all(self) -> list[list[str]]:
        raise NotImplementedError

    def _read_top(self, rows: int) -> list[list[str]]:
        return self._read_all()[:rows]

    def _write_cells(self, cells: list[tuple[int, int, str]]) -> None:
        """Write (row, column, value) cells, 1-based, growing the sheet if needed."""
        raise NotImplementedError

    def _insert_header(self, header: list[str]) -> None:
        """Insert `header` as a new first row, moving everything down one."""
        raise NotImplementedError

    def _append_row(self, values: list[str]) -> int:
        """Add a row after the last one with anything in it; returns its number."""
        raise NotImplementedError


def _cell(row: list[str], col: int) -> str:
    return row[col - 1].strip() if col - 1 < len(row) else ""


def _numbers_without_header(rows: list[list[str]]) -> bool:
    """Numbers pasted straight into the first column, with no header above them."""
    first = next((row[0] for row in rows if row and row[0].strip()), "")
    return normalize_phone(first) is not None
