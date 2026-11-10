"""A month of survey results as a report: calls, water supply, and the same by district, village and age.

Run from agent/:
    uv run python -m agent.report                    # this month
    uv run python -m agent.report --month 2026-10    # another month
    uv run python -m agent.report --no-write         # only print it here

It reads the sheet agent/.env names (GOOGLE_SHEET_ID, else SURVEY_CSV), prints the report, and writes
it beside the contacts: a tab "Report 2026-11" at the end of the same Google spreadsheet, or
contacts-report-2026-11.csv next to a CSV. Run again, the tab is rewritten in place, so charts drawn
on it once keep working. A number belongs to the month of its last call (the sheet's Month column).
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from statistics import mean

from dotenv import load_dotenv

from agent.settings import now, stamp
from agent.sheets import Contact, SheetError, open_sheet
from agent.sheets.base import Cell
from agent.survey.answers import NO, UNCLEAR, YES

STATUSES = (
    ("completed", "Completed"),
    ("partial", "Partial: hung up or ended early"),
    ("busy", "Busy: to call again"),
    ("no_answer", "No answer"),
    ("declined", "Didn't want to take part"),
    ("failed", "Failed: line or number problem"),
    ("calling", "Being called now"),
)
TALKED = ("completed", "partial")  # the calls that have answers in them
NOT_GIVEN = "(not given)"

HOW_OFTEN: tuple[tuple[str, Callable[[float], bool]], ...] = (
    ("Every day", lambda days: days <= 1),
    ("Every 2 days (એકાંતરે)", lambda days: 1 < days <= 2),
    ("Every 3 to 6 days", lambda days: 2 < days < 7),
    ("Once a week or less often", lambda days: days >= 7),
)
HOW_LONG: tuple[tuple[str, Callable[[int], bool]], ...] = (
    ("Under 1 hour", lambda minutes: minutes < 60),
    ("1 to 2 hours", lambda minutes: 60 <= minutes <= 120),
    ("More than 2 hours", lambda minutes: minutes > 120),
)
AGES: tuple[tuple[str, Callable[[int], bool]], ...] = (
    ("Under 30", lambda age: age < 30),
    ("30 to 44", lambda age: 30 <= age < 45),
    ("45 to 59", lambda age: 45 <= age < 60),
    ("60 and over", lambda age: age >= 60),
)


@dataclass(frozen=True)
class Person:
    """One row of the month, with what the report needs read out of its cells."""

    status: str
    district: str
    village: str
    water: bool | None
    days: float | None  # every how many days water comes
    minutes: int | None  # how long it runs on a day it comes
    age: int | None

    @classmethod
    def of(cls, contact: Contact) -> Person:
        v = contact.values
        minutes = _number(v.get("minutes_per_day"))
        age = _number(v.get("age"))
        return cls(
            status=contact.status,
            district=_place(v.get("district")),
            village=_place(v.get("village")),
            water={YES: True, NO: False}.get(v.get("water_supply", "").strip()),
            days=_number(v.get("days_between")) or _days_in(v.get("frequency", "")),
            minutes=round(minutes) if minutes is not None else _minutes_in(v.get("duration", "")),
            age=round(age) if age is not None else None,
        )


def in_month(contact: Contact, month: str) -> bool:
    """Called, and last called in `month` ("2026-11"). Rows from before the Month column existed go by
    their Last call."""
    called_in = contact.values.get("month", "").strip() or contact.values.get("last_call", "").strip()[:7]
    return bool(contact.status) and called_in == month


def build_report(contacts: Iterable[Contact], month: str, made_at: str) -> list[list[Cell]]:
    """The report as rows of cells: a title, then one small table after another."""
    people = [Person.of(c) for c in contacts if in_month(c, month)]
    talked = [p for p in people if p.status in TALKED]
    with_water = [p for p in talked if p.water]
    rows: list[list[Cell]] = [
        [f"Water-supply survey, {month}"],
        ["Made", made_at],
        ["Numbers called", len(people)],
        ["Spoke to us", len(talked)],
        [],
    ]
    calls = Counter(p.status for p in people)
    rows += _counted(
        "Calls",
        [(label, calls[key]) for key, label in STATUSES if key != "calling" or calls[key]],
        len(people),
    )
    yes, no = sum(p.water is True for p in talked), sum(p.water is False for p in talked)
    rows += _counted(
        "Does water come?",
        [("Water comes", yes), ("No water", no), ("Didn't say", len(talked) - yes - no)],
        len(talked),
    )
    rows += _bucketed("How often it comes (people with water)", HOW_OFTEN, [p.days for p in with_water])
    rows.append(["Average: every how many days", _average(p.days for p in with_water)])
    rows.append([])
    rows += _bucketed("Time per day (people with water)", HOW_LONG, [p.minutes for p in with_water])
    rows.append(["Average minutes per day", _average(p.minutes for p in with_water)])
    rows.append([])
    rows += _by_place("By district", talked, key=lambda p: (p.district,))
    rows += _by_place("By village", talked, key=lambda p: (p.village, p.district), extra=["District"])
    rows += _bucketed("Age", AGES, [p.age for p in talked])
    rows.append(["Average age", _average(p.age for p in talked)])
    return rows


def as_text(rows: list[list[Cell]]) -> str:
    """The report for a terminal: the first column left, the numbers right."""
    lines = []
    for row in rows:
        if not row:
            lines.append("")
            continue
        first, rest = str(row[0]), [_shown(cell) for cell in row[1:]]
        lines.append(f"{first:<40}" + "".join(f"{cell:>16}" for cell in rest))
    return "\n".join(lines).rstrip()


# Tables --------------------------------------------------------------------------------------------


def _counted(title: str, counts: list[tuple[str, int]], total: int) -> list[list[Cell]]:
    rows: list[list[Cell]] = [[title, "People", "Share (%)"]]
    rows += [[label, n, _share(n, total)] for label, n in counts]
    return [*rows, []]


def _bucketed(title: str, buckets: tuple[tuple[str, Callable], ...], values: list) -> list[list[Cell]]:
    known = [v for v in values if v is not None]
    counts = [(label, sum(1 for v in known if fits(v))) for label, fits in buckets]
    counts.append((NOT_GIVEN, len(values) - len(known)))
    return _counted(title, counts, len(values))[:-1]  # the average follows, before the gap


def _by_place(
    title: str,
    people: list[Person],
    *,
    key: Callable[[Person], tuple[str, ...]],
    extra: list[str] | None = None,
) -> list[list[Cell]]:
    groups: dict[tuple[str, ...], list[Person]] = {}
    for person in people:
        groups.setdefault(key(person), []).append(person)
    header: list[Cell] = [
        title, *(extra or []), "People", "Water comes", "Water comes (%)", "Every N days", "Minutes per day",
    ]  # fmt: skip
    rows: list[list[Cell]] = [header]
    for place, group in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        comes = [p for p in group if p.water]
        rows.append(
            [
                *(name or NOT_GIVEN for name in place),
                len(group),
                len(comes),
                _share(len(comes), sum(p.water is not None for p in group)),
                _average(p.days for p in comes),
                _average(p.minutes for p in comes),
            ]
        )
    return [*rows, []]


# Reading cells -------------------------------------------------------------------------------------


def _place(text: str | None) -> str:
    text = " ".join((text or "").split())
    return "" if text in ("", UNCLEAR) else text


def _number(text: str | None) -> float | None:
    """ "2", "3.5", or "3,5" from a sheet with a comma for the decimal point."""
    text = (text or "").strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


_EVERY_N_DAYS = re.compile(r"દર\s*(\d+(?:\.\d+)?)\s*દિવસે")
_MINUTES = re.compile(r"(\d+)\s*મિનિટ")


def _days_in(text: str) -> float | None:
    """From the Gujarati column, for rows written before the number column: "એકાંતરે (દર 2 દિવસે)"."""
    if text.strip().startswith("રોજ"):
        return 1.0
    match = _EVERY_N_DAYS.search(text)
    return float(match.group(1)) if match else None


def _minutes_in(text: str) -> int | None:
    """ "અડધો કલાક (30 મિનિટ)", "45 મિનિટ", "આખો દિવસ"."""
    if text.strip().startswith("આખો દિવસ"):
        return 1440
    found = _MINUTES.findall(text)
    return int(found[-1]) if found else None


def _share(n: int, total: int) -> Cell:
    return round(100 * n / total, 1) if total else ""


def _average(values: Iterable[float | int | None]) -> Cell:
    known = [v for v in values if v is not None]
    return round(mean(known), 1) if known else ""


def _shown(cell: Cell) -> str:
    return f"{cell:g}" if isinstance(cell, float) else str(cell)


# Command ---------------------------------------------------------------------------------------------


async def run(month: str, *, write: bool = True) -> int:
    sheet = open_sheet()
    if sheet is None:
        print("No sheet: set GOOGLE_SHEET_ID (or SURVEY_CSV) in agent/.env")
        return 1
    try:
        contacts = await sheet.contacts()
        rows = build_report(contacts, month, stamp())
        print(as_text(rows))
        if write:
            print(f"\nWritten to {await sheet.write_tab(f'Report {month}', rows)}")
    except SheetError as e:
        print(e)
        return 1
    return 0


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="python -m agent.report", description=__doc__.splitlines()[0])
    parser.add_argument("--month", help="YYYY-MM; this month (in SURVEY_TIMEZONE) if left out")
    parser.add_argument("--no-write", action="store_true", help="print the report without writing it")
    args = parser.parse_args()
    month = args.month or f"{now():%Y-%m}"
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        parser.error(f"--month is a year and month, like 2026-11 (got {month!r})")
    sys.stdout.reconfigure(encoding="utf-8")  # Gujarati place names, on a Windows terminal too
    raise SystemExit(asyncio.run(run(month, write=not args.no_write)))


if __name__ == "__main__":
    main()
