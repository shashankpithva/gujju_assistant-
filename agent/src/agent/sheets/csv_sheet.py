"""A contact sheet in a CSV file, for running the survey on one computer without Google.

The dialer and the agent are separate processes that both write to the file, so every change takes
a lock file and rewrites the CSV atomically (a temporary file, then a rename). The file is UTF-8 with
a byte order mark, which Excel needs to show Gujarati instead of mojibake.
"""

from __future__ import annotations

import contextlib
import csv
import os
import re
import time
from collections.abc import Iterator
from pathlib import Path

from agent.sheets.base import Cell, SheetError, TableSheet

LOCK_WAIT_SECONDS = 10.0
STALE_LOCK_SECONDS = 30.0  # a lock left behind by a process that crashed mid-write


class CsvSheet(TableSheet):
    def __init__(self, path: Path | str) -> None:
        super().__init__()
        self._path = Path(path).expanduser()

    @property
    def ref(self) -> str:
        return f"csv:{self._path.resolve()}"

    @property
    def label(self) -> str:
        return self._path.name

    @contextlib.contextmanager
    def _exclusive(self) -> Iterator[None]:
        lock = self._path.with_name(self._path.name + ".lock")
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                break
            except FileExistsError:
                with contextlib.suppress(FileNotFoundError):
                    if time.time() - lock.stat().st_mtime > STALE_LOCK_SECONDS:
                        lock.unlink(missing_ok=True)
                        continue
                if time.monotonic() > deadline:
                    raise SheetError(
                        f"{self._path.name} has been locked for {LOCK_WAIT_SECONDS:.0f} s. If nothing else "
                        f"is running, delete {lock.name}."
                    ) from None
                time.sleep(0.05)
        try:
            yield
        finally:
            lock.unlink(missing_ok=True)

    def _read_all(self) -> list[list[str]]:
        if not self._path.exists():
            return []
        with self._path.open(newline="", encoding="utf-8-sig") as source:
            return [list(row) for row in csv.reader(source)]

    def _write_all(self, rows: list[list[Cell]], path: Path | None = None) -> None:
        path = path or self._path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        with temporary.open("w", newline="", encoding="utf-8-sig") as target:
            csv.writer(target).writerows(rows)
        try:
            os.replace(temporary, path)
        except PermissionError as e:  # Windows: the file is open in Excel
            temporary.unlink(missing_ok=True)
            raise SheetError(f"Can't write {path.name}: close it in Excel (or any other program).") from e

    def _write_cells(self, cells: list[tuple[int, int, Cell]]) -> None:
        rows: list[list[Cell]] = list(self._read_all())
        for row, col, value in cells:
            while len(rows) < row:
                rows.append([])
            line = rows[row - 1]
            while len(line) < col:
                line.append("")
            line[col - 1] = value
        self._write_all(rows)

    def _insert_header(self, header: list[str]) -> None:
        self._write_all([header, *self._read_all()])

    def _append_row(self, values: list[Cell]) -> int:
        rows: list[list[Cell]] = list(self._read_all())
        while rows and not any(str(cell).strip() for cell in rows[-1]):
            rows.pop()
        rows.append(values)
        self._write_all(rows)
        return len(rows)

    def _write_tab(self, title: str, rows: list[list[Cell]]) -> str:
        """A CSV of its own beside this one: contacts.csv and "Report 2026-11" make
        contacts-report-2026-11.csv, which Excel opens with the Gujarati intact."""
        slug = re.sub(r"[^0-9A-Za-z]+", "-", title).strip("-").lower() or "report"
        path = self._path.with_name(f"{self._path.stem}-{slug}.csv")
        self._write_all(rows, path)
        return str(path)
