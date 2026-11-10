"""The monthly report: which rows count, and the numbers in each table."""

from agent.report import as_text, build_report, in_month, run
from agent.sheets import Contact, CsvSheet

MONTH = "2026-11"


def person(status="completed", month=MONTH, **values) -> Contact:
    return Contact(2, "9876543210", {"status": status, "month": month, **values})


def table(rows, title):
    """One table of the report, by its title, up to the gap after it: {label: the other cells}."""
    start = next(i for i, row in enumerate(rows) if row and row[0] == title)
    end = next((i for i in range(start, len(rows)) if not rows[i]), len(rows))
    return {row[0]: row[1:] for row in rows[start + 1 : end]}


def test_a_month_holds_the_numbers_last_called_in_it():
    assert in_month(person(), MONTH)
    assert not in_month(person(month="2026-10"), MONTH)
    assert not in_month(person(status=""), MONTH)  # not called yet
    no_month_column = Contact(2, "9", {"status": "busy", "last_call": "2026-11-03 10:00"})
    assert in_month(no_month_column, MONTH)


def test_calls_are_counted_with_their_share():
    contacts = [person(), person(), person("busy"), person("no_answer"), person(month="2026-10")]
    rows = build_report(contacts, MONTH, "2026-11-30 18:00")
    assert ["Numbers called", 4] in rows and ["Spoke to us", 2] in rows
    calls = table(rows, "Calls")
    assert calls["Completed"] == [2, 50.0] and calls["Busy: to call again"] == [1, 25.0]
    assert "Being called now" not in calls  # only when someone is


def test_water_how_often_and_how_long():
    contacts = [
        person(water_supply="હા", days_between="1", minutes_per_day="30"),
        person(water_supply="હા", days_between="2", minutes_per_day="90"),
        person(water_supply="હા", days_between="7", minutes_per_day="180"),
        person(water_supply="ના"),
        person("partial", name="રમેશ"),  # hung up before the water question
    ]
    rows = build_report(contacts, MONTH, "now")
    water = table(rows, "Does water come?")
    assert water == {"Water comes": [3, 60.0], "No water": [1, 20.0], "Didn't say": [1, 20.0]}
    often = table(rows, "How often it comes (people with water)")
    assert often["Every day"][0] == often["Every 2 days (એકાંતરે)"][0] == 1
    assert often["Once a week or less often"][0] == 1
    assert ["Average: every how many days", 3.3] in rows
    assert table(rows, "Time per day (people with water)")["1 to 2 hours"] == [1, 33.3]
    assert ["Average minutes per day", 100.0] in rows


def test_rows_from_before_the_number_columns_are_read_from_the_gujarati():
    older = person(water_supply="હા", frequency="એકાંતરે (દર 2 દિવસે)", duration="અડધો કલાક (30 મિનિટ)")
    daily = person(water_supply="હા", frequency="રોજ", duration="45 મિનિટ")
    rows = build_report([older, daily], MONTH, "now")
    assert ["Average: every how many days", 1.5] in rows and ["Average minutes per day", 37.5] in rows


def test_by_district_and_village_biggest_first():
    contacts = [
        person(district="અમરેલી", village="ખાંભા", water_supply="હા", days_between="2", minutes_per_day="60"),
        person(district="અમરેલી", village="ખાંભા", water_supply="ના"),
        person(district="અમરેલી", village="ધારી", water_supply="હા", days_between="4", minutes_per_day="30"),
        person(district="(સ્પષ્ટ નથી)", water_supply="હા"),
    ]
    rows = build_report(contacts, MONTH, "now")
    districts = table(rows, "By district")
    assert list(districts) == ["અમરેલી", "(not given)"]
    assert districts["અમરેલી"] == [3, 2, 66.7, 3.0, 45.0]
    assert table(rows, "By village")["ખાંભા"] == ["અમરેલી", 2, 1, 50.0, 2.0, 60.0]


def test_ages_in_groups():
    ages_said = ["25", "44", "45", "70", "(સ્પષ્ટ નથી)"]
    rows = build_report([person(age=a) for a in ages_said], MONTH, "now")
    ages = table(rows, "Age")
    groups = ("Under 30", "30 to 44", "45 to 59", "60 and over", "(not given)")
    assert [ages[g][0] for g in groups] == [1, 1, 1, 1, 1]
    assert ["Average age", 46.0] in rows


def test_an_empty_month_has_no_shares_or_averages():
    rows = build_report([], MONTH, "now")
    assert table(rows, "Calls")["Completed"] == [0, ""] and ["Average age", ""] in rows
    assert "Water-supply survey, 2026-11" in as_text(rows)


async def test_the_command_reads_the_sheet_and_writes_the_report(scratch, monkeypatch, capsys):
    path = scratch / "contacts.csv"
    called = {
        "phone": "9876543210",
        "status": "completed",
        "last_call": "2026-11-10 18:12",
        "water_supply": "હા",
        "days_between": "2",
        "district": "અમરેલી",
    }
    await CsvSheet(path).append(called)
    monkeypatch.setenv("SURVEY_CSV", str(path))
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    assert await run(MONTH) == 0
    printed = capsys.readouterr().out
    assert "Numbers called" in printed and "contacts-report-2026-11.csv" in printed
    report = (scratch / "contacts-report-2026-11.csv").read_text(encoding="utf-8-sig")
    assert "અમરેલી" in report
