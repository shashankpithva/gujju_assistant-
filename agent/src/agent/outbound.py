"""Placing the call: what a job asks for, dialing it through the SIP trunk, and reading a failure.

The dialer (agent/dialer.py) creates one LiveKit job per number, with JSON metadata saying who to call
and which row of which sheet the answers go to. A job without metadata is a test call: the console,
or a browser that joined a room itself.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from uuid import uuid4

from google.protobuf.duration_pb2 import Duration
from livekit import api
from livekit.agents import JobContext

from agent.phone import normalize_phone

CALLEE = "callee"  # the participant identity of the person called
DEFAULT_RING_SECONDS = 35  # Indian networks ring for 30 to 45 s before giving up themselves


def new_call_id() -> str:
    """A fresh id for one conversation: in every log line and in the sheet's Call ID column."""
    return f"call_{uuid4().hex}"


@dataclass(frozen=True)
class CallRequest:
    phone: str | None = None  # E.164; None for a test call
    row: int | None = None  # the sheet row the answers go to; None adds a row (test calls)
    sheet: str | None = None  # the sheet, as sheets.open_sheet takes it; None uses agent/.env's
    attempt: int = 1

    @property
    def outbound(self) -> bool:
        return self.phone is not None

    @classmethod
    def from_metadata(cls, metadata: str | None) -> CallRequest:
        """The dialer's metadata: {"phone": "+91...", "row": 5, "sheet": "google:<id>", "attempt": 1}."""
        if not metadata or not metadata.strip():
            return cls()
        data = json.loads(metadata)
        if not isinstance(data, dict):
            raise ValueError("job metadata must be a JSON object")
        phone = None
        if raw := data.get("phone"):
            phone = normalize_phone(str(raw))
            if phone is None:
                raise ValueError(f"not a phone number: {raw!r}")
        row = data.get("row")
        return cls(
            phone=phone,
            row=int(row) if row is not None else None,
            sheet=str(data["sheet"]) if data.get("sheet") else None,
            attempt=int(data.get("attempt") or 1),
        )

    def metadata(self) -> str:
        return json.dumps(
            {"phone": self.phone, "row": self.row, "sheet": self.sheet, "attempt": self.attempt}
        )


async def dial(ctx: JobContext, phone: str, *, max_call_seconds: float) -> None:
    """Ring `phone` and return once they pick up. Raises api.SipCallError when they don't."""
    trunk = os.getenv("SIP_OUTBOUND_TRUNK_ID", "").strip()
    if not trunk:
        raise MissingTrunk("SIP_OUTBOUND_TRUNK_ID isn't set: create an outbound trunk (docs/agent.md)")
    request = api.CreateSIPParticipantRequest(
        room_name=ctx.room.name,
        sip_trunk_id=trunk,
        sip_call_to=phone,
        participant_identity=CALLEE,
        participant_name="Survey call",
        wait_until_answered=True,
        ringing_timeout=Duration(seconds=int(os.getenv("RING_SECONDS", str(DEFAULT_RING_SECONDS)))),
        # A hard stop on the phone network's side too, a minute after the agent's own limit.
        max_call_duration=Duration(seconds=int(max_call_seconds) + 60),
    )
    if caller_id := os.getenv("SIP_FROM_NUMBER", "").strip():
        request.sip_number = caller_id
    await ctx.api.sip.create_sip_participant(request)


class MissingTrunk(RuntimeError):
    pass


def outcome_of_failed_dial(error: Exception) -> tuple[str, str]:
    """The sheet status and a note for a call that never connected."""
    if isinstance(error, MissingTrunk):
        return "failed", str(error)
    code = getattr(error, "sip_status_code", None)
    said = f"{code} {getattr(error, 'sip_status', None) or ''}".strip()
    if code in (486, 600, 603):
        return "busy", f"Busy or rejected ({said})"
    if code in (408, 480, 487):
        return "no_answer", f"No answer ({said})"
    if code in (404, 410, 484, 485, 604):
        return "failed", f"Number not reachable ({said})"
    if code in (401, 403, 407):
        return "failed", f"The phone provider refused the call: check the SIP trunk's login ({said})"
    if code is not None:
        return "failed", f"Call failed ({said})"
    return "failed", f"Call failed: {error}"
