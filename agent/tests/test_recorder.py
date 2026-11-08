"""Answers reach the sheet during the call, in order, and a sheet problem never breaks the call."""

import asyncio

from agent.survey.recorder import TEST_CALL, SheetRecorder


class RecordingSheet:
    label = "test sheet"
    ref = "test:sheet"

    def __init__(self, *, fail: int = 0, delay: float = 0.0) -> None:
        self.updates: list[tuple[int, dict]] = []
        self.appends: list[dict] = []
        self.fail = fail
        self.delay = delay

    async def update(self, row, values):
        await asyncio.sleep(self.delay)
        if self.fail:
            self.fail -= 1
            raise RuntimeError("Google is down")
        self.updates.append((row, dict(values)))

    async def append(self, values):
        self.appends.append(dict(values))
        return 9

    async def contacts(self):
        return []


async def test_answers_are_written_as_they_come_and_the_last_write_has_everything():
    sheet = RecordingSheet(delay=0.01)
    recorder = SheetRecorder(sheet, 5, phone="+919876543210")
    recorder.write({"name": "રમેશ"})
    recorder.write({"village": "ખાંભા"})  # while the first is on its way: merged into the next write
    await recorder.close({"status": "completed"})
    rows = {row for row, _ in sheet.updates}
    merged = {k: v for _, values in sheet.updates for k, v in values.items()}
    assert rows == {5}
    assert merged == {"name": "રમેશ", "village": "ખાંભા", "status": "completed"}


async def test_a_failed_write_is_retried_with_the_next_one():
    sheet = RecordingSheet(fail=1)
    recorder = SheetRecorder(sheet, 5, phone=None)
    recorder.write({"name": "રમેશ"})
    await asyncio.sleep(0.01)
    assert sheet.updates == []
    await recorder.close({"status": "partial"})
    assert sheet.updates == [(5, {"name": "રમેશ", "status": "partial"})]


async def test_a_sheet_that_never_works_doesnt_hang_the_end_of_the_call():
    sheet = RecordingSheet(fail=100)
    recorder = SheetRecorder(sheet, 5, phone=None)
    recorder.write({"name": "x"})
    await asyncio.wait_for(recorder.close({"status": "partial"}), 2)


async def test_a_test_call_adds_its_own_row_then_writes_to_it():
    sheet = RecordingSheet()
    recorder = SheetRecorder(sheet, None, phone=None)
    recorder.write({"status": "calling"})
    await asyncio.sleep(0.01)
    recorder.write({"name": "રમેશ"})
    await recorder.close({"status": "completed"})
    assert sheet.appends == [{"phone": TEST_CALL, "status": "calling"}]
    assert sheet.updates and all(row == 9 for row, _ in sheet.updates)
    assert recorder.row == 9


async def test_with_no_sheet_nothing_is_written():
    recorder = SheetRecorder(None, None, phone=None)
    assert not recorder.enabled
    recorder.write({"name": "x"})
    await recorder.close({"status": "completed"})


async def test_nothing_is_queued_after_the_final_write():
    sheet = RecordingSheet()
    recorder = SheetRecorder(sheet, 2, phone=None)
    await recorder.close({"status": "completed"})
    recorder.write({"name": "late"})
    await asyncio.sleep(0.01)
    assert sheet.updates == [(2, {"status": "completed"})]
