"""The dialer: who gets called, and what the sheet says when a call never reports back."""

import asyncio
import json
from datetime import timedelta

import pytest
from livekit import api

from agent import dialer
from agent.settings import now, stamp
from agent.sheets import Contact, CsvSheet


def contact(status: str = "", attempts: int = 0, last_call: str = "") -> Contact:
    values = {"status": status, "attempts": str(attempts), "last_call": last_call}
    return Contact(2, "9876543210", values)


@pytest.mark.parametrize(
    ("status", "attempts", "due"),
    [
        ("", 0, True),
        ("no_answer", 1, True),
        ("busy", 1, True),
        ("failed", 1, True),
        ("no_answer", 2, False),  # out of tries
        ("completed", 1, False),
        ("partial", 1, False),
        ("declined", 1, False),
    ],
)
def test_who_gets_called(status, attempts, due):
    assert dialer.due(contact(status, attempts), max_attempts=2) is due


def test_a_call_in_progress_is_left_alone_unless_it_was_left_behind():
    assert not dialer.due(contact("calling", 1, stamp()), max_attempts=2)
    long_ago = stamp(now() - dialer.STUCK_AFTER - timedelta(minutes=1))
    assert dialer.due(contact("calling", 1, long_ago), max_attempts=2)


class FakeDispatches:
    def __init__(self, polls: list) -> None:
        self.polls = polls  # what each get_dispatch returns, in turn
        self.created: list[api.CreateAgentDispatchRequest] = []

    async def create_dispatch(self, request):
        self.created.append(request)
        return api.AgentDispatch(id="AD_1", room=request.room, agent_name=request.agent_name)

    async def get_dispatch(self, _dispatch_id, _room):
        result = self.polls.pop(0) if self.polls else None
        if isinstance(result, Exception):
            raise result
        return result


class FakeRooms:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_room(self, request):
        self.deleted.append(request.room)


class FakeLiveKit:
    def __init__(self, polls: list) -> None:
        self.agent_dispatch = FakeDispatches(polls)
        self.room = FakeRooms()


def running() -> api.AgentDispatch:
    job = api.Job(state=api.JobState(status=api.JobStatus.JS_RUNNING))
    return api.AgentDispatch(id="AD_1", state=api.AgentDispatchState(jobs=[job]))


def finished() -> api.AgentDispatch:
    job = api.Job(state=api.JobState(status=api.JobStatus.JS_SUCCESS))
    return api.AgentDispatch(id="AD_1", state=api.AgentDispatchState(jobs=[job]))


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(dialer, "POLL_SECONDS", 0.001)


async def test_a_call_ends_when_its_room_is_gone_or_its_job_has_finished():
    assert await dialer.wait_for_call(FakeLiveKit([running(), None]), "AD_1", "r", timeout=60) == "ended"
    assert (
        await dialer.wait_for_call(FakeLiveKit([running(), finished()]), "AD_1", "r", timeout=60) == "ended"
    )
    gone = api.ServerError(api.ServerErrorCode.NOT_FOUND, "no room", status=404)
    assert await dialer.wait_for_call(FakeLiveKit([gone]), "AD_1", "r", timeout=60) == "ended"


async def test_no_agent_taking_the_call_is_noticed(monkeypatch):
    monkeypatch.setattr(dialer, "AGENT_JOIN_SECONDS", 0.01)
    waiting = api.AgentDispatch(id="AD_1")
    lk = FakeLiveKit([waiting] * 1000)
    assert await dialer.wait_for_call(lk, "AD_1", "r", timeout=60) == "no_agent"
    assert lk.room.deleted == ["r"]


async def test_place_call_marks_the_row_and_sends_the_agent_who_to_call(scratch, monkeypatch):
    monkeypatch.setenv("AGENT_NAME", "survey-test")
    path = scratch / "s.csv"
    path.write_text("Phone\n9876543210\n", encoding="utf-8")
    sheet = CsvSheet(path)
    await sheet.contacts()

    lk = FakeLiveKit([None])

    async def agent_finishes(_lk, _id, _room, *, timeout):  # what the agent writes when it's done
        await sheet.update(2, {"status": "completed", "name": "રમેશ"})
        return "ended"

    monkeypatch.setattr(dialer, "wait_for_call", agent_finishes)
    status = await dialer.place_call(lk, sheet, 2, "+919876543210", 1)
    assert status == "completed"
    (request,) = lk.agent_dispatch.created
    assert request.agent_name == "survey-test"
    assert json.loads(request.metadata) == {
        "phone": "+919876543210",
        "row": 2,
        "sheet": sheet.ref,
        "attempt": 1,
    }
    (row,) = await sheet.contacts()
    assert row.attempts == 1 and row.values["last_call"]


async def test_a_call_that_never_reports_back_is_marked_failed_with_the_reason(scratch, monkeypatch):
    path = scratch / "s.csv"
    path.write_text("Phone\n9876543210\n", encoding="utf-8")
    sheet = CsvSheet(path)
    await sheet.contacts()

    async def nobody_came(*_args, **_kwargs):
        return "no_agent"

    monkeypatch.setattr(dialer, "wait_for_call", nobody_came)
    assert await dialer.place_call(FakeLiveKit([]), sheet, 2, "+919876543210", 1) == "failed"
    (row,) = await sheet.contacts()
    assert row.status == "failed" and "agent.main dev" in row.values["notes"]


def test_run_calls_each_due_number_once_and_skips_what_isnt_a_number(scratch, monkeypatch, capsys):
    path = scratch / "s.csv"
    path.write_text("Phone,Status\n9876543210,\nnot a number,\n9876500000,completed\n", encoding="utf-8")
    monkeypatch.setenv("SURVEY_CSV", str(path))
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.setenv(name, "test")
    called = []

    async def fake_place_call(_lk, _sheet, row, phone, attempt):
        called.append((row, phone, attempt))
        return "completed"

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(dialer, "place_call", fake_place_call)
    monkeypatch.setattr(dialer.api, "LiveKitAPI", lambda: Client())
    assert dialer.main(["run", "--gap", "0", "--any-time"]) == 0
    assert called == [(2, "+919876543210", 1)]
    rows = {c.row: c for c in asyncio.run(CsvSheet(path).contacts())}
    assert rows[3].status == "failed" and rows[3].values["notes"] == "Not a phone number"
    assert "2 to call now" in capsys.readouterr().out


def test_dry_run_only_lists(scratch, monkeypatch, capsys):
    path = scratch / "s.csv"
    path.write_text("Phone\n9876543210\n", encoding="utf-8")
    monkeypatch.setenv("SURVEY_CSV", str(path))
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    assert dialer.main(["run", "--dry-run"]) == 0
    assert "row 2: 9876543210 (not called yet)" in capsys.readouterr().out


def test_calls_only_go_out_in_calling_hours(monkeypatch):
    from datetime import datetime

    from agent.settings import survey_timezone

    monkeypatch.delenv("SURVEY_CALL_HOURS", raising=False)
    assert dialer.call_hours() == (9, 21)
    monkeypatch.setattr(dialer, "now", lambda: datetime(2026, 11, 8, 22, 30, tzinfo=survey_timezone()))
    assert "--any-time" in dialer.outside_call_hours()
    monkeypatch.setattr(dialer, "now", lambda: datetime(2026, 11, 8, 10, 0, tzinfo=survey_timezone()))
    assert dialer.outside_call_hours() is None
    monkeypatch.setenv("SURVEY_CALL_HOURS", "0-24")
    assert dialer.call_hours() == (0, 24)
    monkeypatch.setenv("SURVEY_CALL_HOURS", "21-9")
    with pytest.raises(SystemExit):
        dialer.call_hours()


def test_no_call_is_placed_at_night(monkeypatch, scratch):
    from datetime import datetime

    from agent.settings import survey_timezone

    monkeypatch.setattr(dialer, "now", lambda: datetime(2026, 11, 8, 23, 0, tzinfo=survey_timezone()))
    monkeypatch.delenv("SURVEY_CALL_HOURS", raising=False)
    with pytest.raises(SystemExit, match="--any-time"):
        dialer.main(["call", "+919876543210"])


def test_setup_trunk_creates_the_phone_line_and_says_what_to_set(monkeypatch, capsys):
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.setenv(name, "test")
    created = []

    class Sip:
        async def create_outbound_trunk(self, request):
            created.append(request.trunk)
            return api.SIPOutboundTrunkInfo(sip_trunk_id="ST_new", name=request.trunk.name)

    class Client:
        sip = Sip()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(dialer.api, "LiveKitAPI", lambda: Client())
    argv = ["setup-trunk", "--address", "sip.example.com", "--number", "98765 43210", "--username", "u"]
    assert dialer.main([*argv, "--password", "p"]) == 0
    (trunk,) = created
    assert trunk.address == "sip.example.com" and list(trunk.numbers) == ["+919876543210"]
    assert trunk.auth_username == "u" and trunk.auth_password == "p"
    assert "SIP_OUTBOUND_TRUNK_ID=ST_new" in capsys.readouterr().out
