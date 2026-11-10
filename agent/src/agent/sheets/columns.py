"""The sheet's columns: what each holds, and how a header is recognised however it's written.

People set up a sheet their own way: "Phone", "Mobile No.", "ફોન નંબર", or a header copied from
here. A column is found by any of its names, in English or Gujarati, and a column the sheet lacks
is added at the end of the header row, so the person running the survey only has to fill in numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    key: str
    header: str  # what a new column is titled
    aliases: tuple[str, ...] = ()


COLUMNS: tuple[Column, ...] = (
    Column(
        "phone",
        "Phone / ફોન નંબર",
        (
            "phone",
            "phone number",
            "phone no",
            "mobile",
            "mobile number",
            "mobile no",
            "number",
            "contact",
            "contact number",
            "ફોન",
            "ફોન નંબર",
            "મોબાઈલ",
            "મોબાઇલ",
            "મોબાઈલ નંબર",
            "મોબાઇલ નંબર",
            "નંબર",
        ),
    ),  # fmt: skip
    Column("name", "Name / નામ", ("name", "naam", "નામ")),
    Column("age", "Age / ઉંમર", ("age", "umar", "umra", "ઉંમર", "ઉમર", "વય")),
    Column("village", "Village / ગામ", ("village", "gaam", "gam", "town", "ગામ")),
    Column("taluka", "Taluka / તાલુકો", ("taluka", "taluko", "tehsil", "તાલુકો", "તાલુકા")),
    Column("district", "District / જિલ્લો", ("district", "jillo", "jilla", "જિલ્લો", "જીલ્લો", "જિલ્લા")),
    Column(
        "water_supply",
        "Water comes? / પાણી આવે છે?",
        ("water comes", "water", "water supply", "pani aave che", "પાણી આવે છે", "પાણી"),
    ),
    Column(
        "frequency",
        "How often / કેટલા દિવસે",
        ("how often", "frequency", "every how many days", "ketla divse", "કેટલા દિવસે", "કેટલા દિવસે આવે છે"),
    ),
    Column(
        "duration",
        "Time per day / દિવસમાં કેટલો સમય",
        ("time per day", "duration", "hours per day", "ketlo samay", "દિવસમાં કેટલો સમય", "કેટલો સમય"),
    ),
    # The same two answers as plain numbers, for charts and averages: the Gujarati columns above say
    # "એકાંતરે (દર 2 દિવસે)", which a spreadsheet can't add up.
    Column("days_between", "Every N days / દર કેટલા દિવસે", ("every n days", "days between", "days")),
    Column("minutes_per_day", "Minutes per day / દિવસમાં મિનિટ", ("minutes per day", "minutes")),
    Column("status", "Status", ("status", "call status", "સ્થિતિ")),
    Column("attempts", "Attempts", ("attempts", "tries", "calls made")),
    Column("last_call", "Last call", ("last call", "last called", "called at", "call time")),
    Column("month", "Month", ("month", "મહિનો")),  # of the last call, "2026-11": for monthly totals
    Column("notes", "Notes", ("notes", "note", "remarks", "નોંધ")),
    Column("call_id", "Call ID", ("call id", "call_id")),
    Column("transcript", "Transcript", ("transcript", "conversation", "વાતચીત")),
)
KEYS: tuple[str, ...] = tuple(c.key for c in COLUMNS)
ANSWER_KEYS = (
    "name", "age", "village", "taluka", "district", "water_supply", "frequency", "duration", "days_between",
    "minutes_per_day",
)  # fmt: skip
# Written as numbers, not text, so a Google Sheet can chart and average them (a CSV has no types:
# Excel reads numbers by itself).
NUMBER_KEYS = ("age", "days_between", "minutes_per_day", "attempts")


def _normal(text: str) -> str:
    text = " ".join(text.lower().replace("_", " ").split())
    return text.strip(" .:?!#*-")


_NAMES: dict[str, str] = {}
for _column in COLUMNS:
    for _name in (_column.header, _column.key, *_column.aliases):
        _NAMES.setdefault(_normal(_name), _column.key)


def column_for(header: str) -> str | None:
    """Which column a header cell names, if any: "Phone", "Village / ગામ", "મોબાઈલ નંબર:"."""
    whole = _normal(header)
    if not whole:
        return None
    if whole in _NAMES:
        return _NAMES[whole]
    for part in re.split(r"[/|()\[\]]", header):  # "Village (ગામ)", "Name / નામ"
        if (key := _NAMES.get(_normal(part))) is not None:
            return key
    return None


@dataclass
class Layout:
    """Where the header is and which column holds what (1-based, as sheets count)."""

    header_row: int
    columns: dict[str, int]
    width: int  # columns in the header row, including any added

    def missing(self) -> list[str]:
        return [key for key in KEYS if key not in self.columns]


HEADER_SEARCH_ROWS = 5  # a title or a note may sit above the header


def find_layout(rows: list[list[str]]) -> Layout | None:
    """The first of the top rows that names a phone column, and every column it names."""
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS], start=1):
        columns: dict[str, int] = {}
        for position, cell in enumerate(row, start=1):
            key = column_for(cell)
            if key is not None and key not in columns:
                columns[key] = position
        if "phone" in columns:
            width = max((i for i, cell in enumerate(row, start=1) if cell.strip()), default=0)
            return Layout(index, columns, width)
    return None


def complete(layout: Layout) -> list[tuple[int, str]]:
    """Add the columns the sheet lacks after its last header cell; returns (column, header) to write."""
    added = []
    for key in layout.missing():
        layout.width += 1
        layout.columns[key] = layout.width
        added.append((layout.width, next(c.header for c in COLUMNS if c.key == key)))
    return added


def new_header() -> list[str]:
    return [c.header for c in COLUMNS]
