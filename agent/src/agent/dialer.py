"""Call the people in the sheet, one after another, and let the agent survey each of them.

    uv run python -m agent.dialer check                  # is everything set up for real calls?
    uv run python -m agent.dialer list                   # who's in the sheet, and how each call went
    uv run python -m agent.dialer run                    # call everyone not called yet
    uv run python -m agent.dialer run --limit 3          # only the next three
    uv run python -m agent.dialer call +919876543210     # add one number to the sheet and call it now
    uv run python -m agent.dialer setup-trunk --address sip.provider.example --number +91...  # once

Calls are only placed between 9 AM and 9 PM in SURVEY_TIMEZONE (SURVEY_CALL_HOURS), unless --any-time.

The agent takes the calls, so it must be running: `uv run python -m agent.main dev` on this computer,
or deployed to LiveKit Cloud with the same AGENT_NAME. For each number the dialer marks the row
"calling", asks LiveKit to send the agent, and waits for the call to end before the next one. The
agent fills in the answers, the status and the transcript as it goes.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from collections.abc import Sequence
from datetime import timedelta
from time import monotonic
from uuid import uuid4

from dotenv import load_dotenv
from livekit import api

from agent.outbound import CallRequest
from agent.phone import normalize_phone, pretty
from agent.settings import agent_name, now, parse_stamp, seconds, stamp
from agent.sheets import CALLING, Contact, ContactSheet, SheetError, open_sheet

POLL_SECONDS = 2.0
# How long a dispatched call may wait for an agent: a deployed agent asleep on the free plan takes
# 10-20 s to wake up.
AGENT_JOIN_SECONDS = 60.0
# A row still "calling" this long after its call started was left behind by a crash: call it again.
STUCK_AFTER = timedelta(minutes=15)
RETRY_STATUSES = ("no_answer", "busy", "failed")
# When calls may be placed, in SURVEY_TIMEZONE: 9 AM to 9 PM, the hours India allows for commercial
# calls. People surveyed at night don't stay surveyed for long.
DEFAULT_CALL_HOURS = "9-21"


def call_hours() -> tuple[int, int]:
    """SURVEY_CALL_HOURS as (first hour, hour calls stop): "9-21" lets calls start until 20:59."""
    text = os.getenv("SURVEY_CALL_HOURS") or DEFAULT_CALL_HOURS
    try:
        start, end = (int(part) for part in text.replace(" ", "").split("-"))
    except ValueError:
        sys.exit(f"SURVEY_CALL_HOURS must look like 9-21, got {text!r}")
    if not 0 <= start < end <= 24:
        sys.exit(f"SURVEY_CALL_HOURS must look like 9-21, got {text!r}")
    return start, end


def outside_call_hours() -> str | None:
    """Why calls can't be placed now, or None if they can."""
    start, end = call_hours()
    if start <= now().hour < end:
        return None
    return (
        f"It's {now():%H:%M} in {now().tzinfo}: calls go out between {start}:00 and {end}:00 "
        f"(SURVEY_CALL_HOURS). Use --any-time to call anyway, for example your own phone."
    )


def due(contact: Contact, *, max_attempts: int, retry: Sequence[str] = RETRY_STATUSES) -> bool:
    """Whether a row should be called now."""
    status = contact.status
    if not status:
        return True
    if status in retry:
        return contact.attempts < max_attempts
    if status == CALLING:  # in progress, unless it has been far too long
        started = parse_stamp(contact.values.get("last_call", ""))
        return started is not None and now() - started > STUCK_AFTER and contact.attempts < max_attempts
    return False  # completed, partial, declined


async def wait_for_call(lk: api.LiveKitAPI, dispatch_id: str, room: str, *, timeout: float) -> str:
    """ "ended", "no_agent" (no agent took the call) or "timeout". The agent deletes the room when it
    hangs up, which takes the dispatch with it."""
    began = monotonic()
    while True:
        await asyncio.sleep(POLL_SECONDS)
        try:
            dispatch = await lk.agent_dispatch.get_dispatch(dispatch_id, room)
        except api.ServerError as e:
            if e.code == api.ServerErrorCode.NOT_FOUND:
                return "ended"
            raise
        if dispatch is None:
            return "ended"
        jobs = list(dispatch.state.jobs)
        finished = (api.JobStatus.JS_SUCCESS, api.JobStatus.JS_FAILED, api.JobStatus.JS_CANCELLED)
        if jobs and all(job.state.status in finished for job in jobs):
            return "ended"
        waited = monotonic() - began
        if (not jobs and waited > AGENT_JOIN_SECONDS) or waited > timeout:
            with contextlib.suppress(api.ServerError):
                await lk.room.delete_room(api.DeleteRoomRequest(room=room))
            return "no_agent" if not jobs else "timeout"


async def place_call(
    lk: api.LiveKitAPI, sheet: ContactSheet | None, row: int | None, phone: str, attempt: int
) -> str:
    """Call one number and wait for the call to end. Returns the status the sheet ended up with."""
    if sheet is not None and row is not None:
        await sheet.update(
            row, {"status": CALLING, "attempts": str(attempt), "last_call": stamp(), "notes": ""}
        )
    room = f"survey-{row or 'test'}-{uuid4().hex[:8]}"
    request = CallRequest(phone=phone, row=row, sheet=sheet.ref if sheet else None, attempt=attempt)
    dispatch = await lk.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(agent_name=agent_name(), room=room, metadata=request.metadata())
    )
    timeout = seconds("MAX_CALL_SECONDS", 240) + seconds("RING_SECONDS", 35) + AGENT_JOIN_SECONDS + 60
    how = await wait_for_call(lk, dispatch.id, room, timeout=timeout)
    if sheet is None or row is None:
        return how
    status = await _status_of(sheet, row)
    if status == CALLING:  # the agent never reported back
        note = {
            "no_agent": (
                f"No agent took the call: run `uv run python -m agent.main dev`, or deploy the agent, "
                f"with AGENT_NAME={agent_name()}"
            ),
            "timeout": "The call ran past its time limit",
        }.get(how, "The agent ended without saving a result: see its log")
        await sheet.update(row, {"status": "failed", "notes": note})
        return "failed"
    return status


async def _status_of(sheet: ContactSheet, row: int) -> str:
    for contact in await sheet.contacts():
        if contact.row == row:
            return contact.status
    return ""


def _numbers(count: int) -> str:
    return f"{count} number{'' if count == 1 else 's'}"


def _livekit() -> api.LiveKitAPI:
    missing = [n for n in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET") if not os.getenv(n)]
    if missing:
        sys.exit(f"Set {', '.join(missing)} in agent/.env (cloud.livekit.io -> Settings -> API keys).")
    return api.LiveKitAPI()


def _sheet() -> ContactSheet:
    try:
        sheet = open_sheet()
    except SheetError as e:
        sys.exit(str(e))
    if sheet is None:
        sys.exit("No sheet: set GOOGLE_SHEET_ID (a Google Sheet) or SURVEY_CSV (a CSV file) in agent/.env.")
    return sheet


# Commands ------------------------------------------------------------------------------------------


async def cmd_run(args: argparse.Namespace) -> int:
    if not args.dry_run and not args.any_time and (why := outside_call_hours()):
        sys.exit(why)
    sheet = _sheet()
    contacts = await sheet.contacts()
    queue = [c for c in contacts if due(c, max_attempts=args.max_attempts)]
    if args.limit:
        queue = queue[: args.limit]
    print(f"{sheet.label}: {_numbers(len(contacts))}, {len(queue)} to call now.")
    if not queue:
        return 0
    if args.dry_run:
        for contact in queue:
            print(f"  row {contact.row}: {contact.phone} ({contact.status or 'not called yet'})")
        return 0
    async with _livekit() as lk:
        for done, contact in enumerate(queue, start=1):
            phone = normalize_phone(contact.phone)
            if phone is None:
                print(f"[{done}/{len(queue)}] row {contact.row}: {contact.phone!r} isn't a phone number")
                await sheet.update(contact.row, {"status": "failed", "notes": "Not a phone number"})
                continue
            print(f"[{done}/{len(queue)}] row {contact.row}: calling {pretty(phone)} ...", flush=True)
            status = await place_call(lk, sheet, contact.row, phone, contact.attempts + 1)
            print(f"           {status}", flush=True)
            if done < len(queue):
                await asyncio.sleep(args.gap)
    return 0


async def cmd_call(args: argparse.Namespace) -> int:
    phone = normalize_phone(args.number)
    if phone is None:
        sys.exit(f"{args.number!r} isn't a phone number.")
    if not args.any_time and (why := outside_call_hours()):
        sys.exit(why)
    sheet: ContactSheet | None = None
    row, attempts = None, 0
    try:
        sheet = open_sheet()
    except SheetError as e:
        sys.exit(str(e))
    if sheet is not None:
        contacts = await sheet.contacts()
        existing = next((c for c in contacts if normalize_phone(c.phone) == phone), None)
        if existing:
            row, attempts = existing.row, existing.attempts
        else:
            row = await sheet.append({"phone": phone})
        print(f"{sheet.label}: row {row}")
    async with _livekit() as lk:
        print(f"calling {pretty(phone)} ...", flush=True)
        print(await place_call(lk, sheet, row, phone, attempts + 1))
    return 0


async def cmd_list(_args: argparse.Namespace) -> int:
    sheet = _sheet()
    contacts = await sheet.contacts()
    print(f"{sheet.label}: {_numbers(len(contacts))}")
    for c in contacts:
        answers = " | ".join(
            c.values.get(k, "")
            for k in ("name", "village", "taluka", "district", "water_supply", "frequency", "duration")
        )
        print(f"  row {c.row:>3}  {c.phone:<16} {c.status or '-':<10} {answers if c.answered else ''}")
    return 0


async def cmd_setup_trunk(args: argparse.Namespace) -> int:
    """Create the LiveKit outbound trunk: the phone line calls go out on, from your SIP provider."""
    numbers = [n for n in (normalize_phone(raw) for raw in args.number) if n]
    if len(numbers) != len(args.number):
        sys.exit("Give each --number in full, with its country code: --number +919876543210")
    trunk = api.SIPOutboundTrunkInfo(
        name=args.name,
        address=args.address,
        numbers=numbers,
        auth_username=args.username or "",
        auth_password=args.password or "",
    )
    async with _livekit() as lk:
        created = await lk.sip.create_outbound_trunk(api.CreateSIPOutboundTrunkRequest(trunk=trunk))
    print(f"Created outbound trunk {created.sip_trunk_id} ({args.name}) via {args.address}.")
    print("Put this line in agent/.env (and the agent's secrets, if it's deployed):")
    print(f"SIP_OUTBOUND_TRUNK_ID={created.sip_trunk_id}")
    return 0


async def cmd_check(_args: argparse.Namespace) -> int:
    ok = True

    def report(good: bool, what: str, detail: str) -> None:
        nonlocal ok
        ok = ok and good
        print(f"  [{'ok' if good else 'FAIL'}] {what}: {detail}")

    print("Checking the setup for survey calls")
    for key, why in (("SARVAM_API_KEY", "Gujarati hearing and voice"),):
        report(bool(os.getenv(key)), key, why if os.getenv(key) else "not set (dashboard.sarvam.ai)")
    llms = [k for k in ("GROQ_API_KEY", "GOOGLE_API_KEY") if os.getenv(k)]
    report(bool(llms), "LLM", ", ".join(llms) if llms else "set GROQ_API_KEY and/or GOOGLE_API_KEY")
    try:
        sheet = open_sheet()
        if sheet is None:
            report(False, "Sheet", "set GOOGLE_SHEET_ID or SURVEY_CSV")
        else:
            contacts = await sheet.contacts()
            bad = [c.row for c in contacts if normalize_phone(c.phone) is None]
            waiting = sum(due(c, max_attempts=2) for c in contacts)
            report(not bad, "Sheet", f"{sheet.label}: {_numbers(len(contacts))}, {waiting} to call")
            if bad:
                print(f"         rows that aren't phone numbers: {', '.join(map(str, bad[:20]))}")
    except Exception as e:
        report(False, "Sheet", str(e))
    if not all(os.getenv(n) for n in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")):
        report(False, "LiveKit", "set LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET")
    else:
        try:
            async with api.LiveKitAPI() as lk:
                await lk.room.list_rooms(api.ListRoomsRequest())
                report(True, "LiveKit", os.getenv("LIVEKIT_URL", ""))
                trunk = os.getenv("SIP_OUTBOUND_TRUNK_ID", "").strip()
                if not trunk:
                    report(
                        False, "Phone line", "set SIP_OUTBOUND_TRUNK_ID (see docs/agent.md: outbound trunk)"
                    )
                else:
                    found = await lk.sip.list_outbound_trunk(api.ListSIPOutboundTrunkRequest())
                    match = next((t for t in found.items if t.sip_trunk_id == trunk), None)
                    if match is None:
                        report(False, "Phone line", f"no outbound trunk {trunk} in this LiveKit project")
                    else:
                        report(
                            True,
                            "Phone line",
                            f"{match.name or trunk} via {match.address}, from {list(match.numbers)}",
                        )
        except Exception as e:
            report(False, "LiveKit", f"can't connect: {e}")
    start, end = call_hours()
    print(f"  [info] Calls go to agents named {agent_name()!r}: the agent must run with the same AGENT_NAME.")
    print(f"  [info] Calls are placed between {start}:00 and {end}:00, {now().tzinfo} (now {now():%H:%M}).")
    print("All set." if ok else "Fix the FAIL lines above, then run this again.")
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Gujarati names on a Windows console
    parser = argparse.ArgumentParser(prog="python -m agent.dialer", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="call everyone in the sheet who hasn't been called yet")
    run.add_argument("--limit", type=int, default=0, help="call at most this many")
    run.add_argument(
        "--max-attempts", type=int, default=2, help="calls per number, counting retries (default 2)"
    )
    run.add_argument("--gap", type=float, default=3.0, help="seconds between calls (default 3)")
    run.add_argument("--dry-run", action="store_true", help="only show who would be called")
    run.add_argument("--any-time", action="store_true", help="call even outside SURVEY_CALL_HOURS")
    call = commands.add_parser("call", help="add a number to the sheet and call it now")
    call.add_argument("number")
    call.add_argument("--any-time", action="store_true", help="call even outside SURVEY_CALL_HOURS")
    commands.add_parser("list", help="show the sheet: numbers, status and answers")
    commands.add_parser("check", help="check the keys, the phone line and the sheet")
    trunk = commands.add_parser("setup-trunk", help="create the outbound phone line in LiveKit (once)")
    trunk.add_argument(
        "--address", required=True, help="your SIP provider's address, e.g. sip.provider.example"
    )
    trunk.add_argument(
        "--number", required=True, action="append", help="the number calls come from (repeatable)"
    )
    trunk.add_argument("--username", help="the SIP login your provider gave you")
    trunk.add_argument("--password", help="its password")
    trunk.add_argument("--name", default="Survey line", help="a name for the trunk in LiveKit")
    args = parser.parse_args(argv)
    handler = {
        "run": cmd_run,
        "call": cmd_call,
        "list": cmd_list,
        "check": cmd_check,
        "setup-trunk": cmd_setup_trunk,
    }[args.command]
    try:
        return asyncio.run(handler(args))
    except SheetError as e:
        print(f"Sheet problem: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped. A call in progress carries on until it ends.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
