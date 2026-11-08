"""The contact sheet: however it's set up, numbers come out and answers go in, in the right cells."""

import asyncio
import csv
import json

import pytest

from agent.sheets import ANSWER_KEYS, CsvSheet, GoogleSheet, SheetError, open_sheet, sheet_id_from
from agent.sheets.columns import column_for, find_layout, new_header


def rows_of(path) -> list[list[str]]:
    with open(path, newline="", encoding="utf-8-sig") as source:
        return list(csv.reader(source))


@pytest.mark.parametrize(
    ("header", "key"),
    [
        ("Phone", "phone"),
        ("Mobile No.", "phone"),
        ("ફોન નંબર", "phone"),
        ("મોબાઈલ નંબર:", "phone"),
        ("Village / ગામ", "village"),
        ("Village (ગામ)", "village"),
        ("taluko", "taluka"),
        ("જીલ્લો", "district"),
        ("Water comes? / પાણી આવે છે?", "water_supply"),
        ("કેટલા દિવસે", "frequency"),
        ("Remarks", "notes"),
        ("Number of taps", None),
        ("", None),
    ],
)
def test_a_column_is_found_by_any_of_its_names(header, key):
    assert column_for(header) == key


def test_the_header_may_sit_below_a_title():
    layout = find_layout([["Water survey, November"], ["", "Phone", "નામ"], ["", "98250 12345", ""]])
    assert layout is not None and layout.header_row == 2
    assert layout.columns == {"phone": 2, "name": 3}


async def test_an_empty_sheet_gets_a_full_header(scratch):
    path = scratch / "new.csv"
    assert await CsvSheet(path).contacts() == []
    assert rows_of(path) == [new_header()]


async def test_numbers_pasted_with_no_header_get_one_above_them(scratch):
    path = scratch / "pasted.csv"
    path.write_text("9876543210\n+91 98765 11111\n", encoding="utf-8")
    contacts = await CsvSheet(path).contacts()
    assert [(c.row, c.phone) for c in contacts] == [(2, "9876543210"), (3, "+91 98765 11111")]
    assert rows_of(path)[0] == new_header()


async def test_the_persons_own_columns_are_kept_and_the_missing_ones_added(scratch):
    path = scratch / "own.csv"
    path.write_text("મોબાઈલ નંબર,ગામ,Remarks\n9825012345,ખાંભા,old note\n", encoding="utf-8")
    sheet = CsvSheet(path)
    (contact,) = await sheet.contacts()
    assert contact.values["village"] == "ખાંભા" and contact.values["notes"] == "old note"
    header = rows_of(path)[0]
    assert header[:3] == ["મોબાઈલ નંબર", "ગામ", "Remarks"]  # untouched
    assert "Name / નામ" in header and "Transcript" in header and "Notes" not in header


async def test_answers_go_into_their_own_cells(scratch):
    path = scratch / "s.csv"
    path.write_text("Phone,Notes\n9876543210,\n9876500000,\n", encoding="utf-8")
    sheet = CsvSheet(path)
    await sheet.contacts()
    await sheet.update(3, {"name": "સીતા", "status": "completed", "attempts": "1"})
    contacts = await CsvSheet(path).contacts()  # read back by a fresh reader, like the dialer
    assert contacts[0].status == "" and contacts[0].attempts == 0
    assert contacts[1].values["name"] == "સીતા" and contacts[1].status == "completed"
    assert contacts[1].attempts == 1 and contacts[1].answered


async def test_an_agent_can_write_without_reading_the_sheet_first(scratch):
    path = scratch / "s.csv"
    path.write_text("Phone\n9876543210\n", encoding="utf-8")
    await CsvSheet(path).update(2, {"district": "અમરેલી", "not_a_column": "x"})
    assert (await CsvSheet(path).contacts())[0].values["district"] == "અમરેલી"


async def test_a_test_call_gets_a_row_of_its_own(scratch):
    path = scratch / "s.csv"
    path.write_text("Phone\n9876543210\n\n\n", encoding="utf-8")
    row = await CsvSheet(path).append({"phone": "(test call)", "status": "calling"})
    assert row == 3  # straight after the last row with anything in it
    assert [c.phone for c in await CsvSheet(path).contacts()] == ["9876543210", "(test call)"]


async def test_a_sheet_without_a_phone_column_says_what_to_do(scratch):
    path = scratch / "bad.csv"
    path.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(SheetError, match="Phone"):
        await CsvSheet(path).contacts()


async def test_the_dialer_and_the_agent_can_write_at_the_same_time(scratch):
    path = scratch / "s.csv"
    path.write_text("Phone\n" + "".join(f"98765000{i:02d}\n" for i in range(20)), encoding="utf-8")
    await CsvSheet(path).contacts()
    writers = [CsvSheet(path) for _ in range(4)]  # separate objects: separate processes, as far as locks go
    await asyncio.gather(
        *(writers[i % 4].update(i + 2, {"name": f"n{i}", "status": "completed"}) for i in range(20))
    )
    contacts = await CsvSheet(path).contacts()
    assert [c.values["name"] for c in contacts] == [f"n{i}" for i in range(20)]  # no write lost
    assert not (scratch / "s.csv.lock").exists()


async def test_a_lock_left_by_a_crash_is_cleared(scratch, monkeypatch):
    import os

    from agent.sheets import csv_sheet

    path = scratch / "s.csv"
    path.write_text("Phone\n9876543210\n", encoding="utf-8")
    lock = scratch / "s.csv.lock"
    lock.write_text("")
    old = lock.stat().st_mtime - csv_sheet.STALE_LOCK_SECONDS - 5
    os.utime(lock, (old, old))
    assert len(await CsvSheet(path).contacts()) == 1


async def test_csv_is_saved_so_excel_shows_gujarati(scratch):
    path = scratch / "s.csv"
    await CsvSheet(path).append({"phone": "9876543210", "name": "રમેશ"})
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # the byte order mark Excel needs


def test_open_sheet_reads_the_reference_the_dialer_passes(monkeypatch, scratch):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.delenv("SURVEY_CSV", raising=False)
    assert open_sheet() is None
    sheet = CsvSheet(scratch / "c.csv")
    assert open_sheet(sheet.ref).label == "c.csv"
    google = open_sheet("google:abc123#Survey")
    assert isinstance(google, GoogleSheet) and google.ref == "google:abc123#Survey"
    with pytest.raises(SheetError):
        open_sheet("ftp:nope")
    monkeypatch.setenv("SURVEY_CSV", str(scratch / "env.csv"))
    assert open_sheet().label == "env.csv"
    monkeypatch.setenv("GOOGLE_SHEET_ID", "https://docs.google.com/spreadsheets/d/1AbC_x-9/edit#gid=0")
    assert open_sheet().ref == "google:1AbC_x-9"  # Google wins, and a whole address works


def test_a_sheet_id_from_its_address():
    assert sheet_id_from("https://docs.google.com/spreadsheets/d/1AbC_x-9/edit?usp=sharing") == "1AbC_x-9"
    assert sheet_id_from(" 1AbC_x-9 ") == "1AbC_x-9"


# Google Sheets, against a stand-in worksheet ----------------------------------------------------


class FakeWorksheet:
    def __init__(self, rows: list[list[str]]) -> None:
        self.rows = [list(r) for r in rows]
        self.col_count = 26
        self.row_count = 1000
        self.batches: list[list[dict]] = []

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def get_values(self, range_name):
        return [list(r) for r in self.rows[: int(range_name.split(":")[1])]]

    def add_cols(self, n):
        self.col_count += n

    def add_rows(self, n):
        self.row_count += n

    def batch_update(self, data, value_input_option=None):
        from gspread.utils import a1_to_rowcol

        assert value_input_option == "RAW"  # "+91..." must stay text
        self.batches.append(data)
        for cell in data:
            row, col = a1_to_rowcol(cell["range"])
            while len(self.rows) < row:
                self.rows.append([])
            while len(self.rows[row - 1]) < col:
                self.rows[row - 1].append("")
            self.rows[row - 1][col - 1] = cell["values"][0][0]

    def insert_row(self, values, index=1, value_input_option=None):
        self.rows.insert(index - 1, list(values))

    def append_row(self, values, value_input_option=None, table_range=None):
        self.rows.append(list(values))
        return {"updates": {"updatedRange": f"Sheet1!A{len(self.rows)}:N{len(self.rows)}"}}


def google_with(rows) -> tuple[GoogleSheet, FakeWorksheet]:
    sheet = GoogleSheet("sheet123", credentials={"client_email": "bot@x.iam.gserviceaccount.com"})
    sheet._worksheet_handle = FakeWorksheet(rows)
    return sheet, sheet._worksheet_handle


async def test_google_sheet_reads_numbers_and_completes_the_header():
    sheet, worksheet = google_with([["Phone", "Name"], ["9876543210", ""], ["", ""], ["+919876500000", ""]])
    contacts = await sheet.contacts()
    assert [(c.row, c.phone) for c in contacts] == [(2, "9876543210"), (4, "+919876500000")]
    assert worksheet.rows[0][:3] == ["Phone", "Name", "Village / ગામ"]
    assert len(worksheet.rows[0]) == 14


async def test_google_sheet_writes_only_the_cells_that_changed():
    sheet, worksheet = google_with([["Phone", "Name", "Status"], ["9876543210", "", ""]])
    await sheet.contacts()
    worksheet.batches.clear()
    await sheet.update(2, {"name": "રમેશ", "status": "completed"})
    assert worksheet.batches == [
        [{"range": "B2", "values": [["રમેશ"]]}, {"range": "C2", "values": [["completed"]]}]
    ]


async def test_google_sheet_grows_when_a_column_is_beyond_its_edge():
    sheet, worksheet = google_with([["Phone"]])
    worksheet.col_count = 5
    await sheet.contacts()
    assert worksheet.col_count >= 14


async def test_google_sheet_appends_a_test_call_and_learns_its_row():
    sheet, worksheet = google_with([["Phone"], ["9876543210"]])
    assert await sheet.append({"phone": "(test call)"}) == 3


async def test_a_google_sheet_that_isnt_shared_says_who_to_share_it_with(monkeypatch):
    import gspread

    class Response:
        status_code = 403
        text = "forbidden"

        def json(self):
            return {"error": {"code": 403, "message": "The caller does not have permission", "status": "x"}}

    class Client:
        def open_by_key(self, _key):
            raise gspread.exceptions.APIError(Response())

    monkeypatch.setattr(gspread, "service_account_from_dict", lambda *a, **k: Client())
    sheet = GoogleSheet("sheet123", credentials={"client_email": "bot@x.iam.gserviceaccount.com"})
    with pytest.raises(SheetError, match="share it with bot@x.iam.gserviceaccount.com"):
        await sheet.contacts()


def test_the_service_account_key_can_come_as_a_file_text_or_base64(monkeypatch, scratch):
    import base64

    from agent.sheets.google_sheet import service_account_info

    key = {"client_email": "bot@x", "private_key": "k"}
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    with pytest.raises(SheetError, match="GOOGLE_SERVICE_ACCOUNT_FILE"):
        service_account_info()
    (scratch / "key.json").write_text(json.dumps(key), encoding="utf-8")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(scratch / "key.json"))
    assert service_account_info() == key
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps(key))
    assert service_account_info() == key
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", base64.b64encode(json.dumps(key).encode()).decode())
    assert service_account_info() == key
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "not json")
    with pytest.raises(SheetError):
        service_account_info()


def test_every_answer_has_a_column():
    assert set(ANSWER_KEYS) == {
        "name",
        "village",
        "taluka",
        "district",
        "water_supply",
        "frequency",
        "duration",
    }
