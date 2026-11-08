"""Placing the call: the request the dialer sends, the SIP dial, and what a failed dial means."""

from types import SimpleNamespace

import pytest
from livekit import api

from agent.outbound import CALLEE, CallRequest, MissingTrunk, dial, new_call_id, outcome_of_failed_dial


def test_the_dialers_request_comes_through_the_job_intact():
    request = CallRequest(phone="+919876543210", row=5, sheet="google:abc#Survey", attempt=2)
    assert CallRequest.from_metadata(request.metadata()) == request
    assert request.outbound


def test_a_job_without_metadata_is_a_test_call():
    assert CallRequest.from_metadata(None) == CallRequest()
    assert CallRequest.from_metadata("  ") == CallRequest()
    assert not CallRequest().outbound


def test_the_number_is_normalized_and_checked():
    assert CallRequest.from_metadata('{"phone": "98765 43210", "row": "7"}').phone == "+919876543210"
    with pytest.raises(ValueError, match="not a phone number"):
        CallRequest.from_metadata('{"phone": "123"}')
    with pytest.raises(ValueError):
        CallRequest.from_metadata("[1, 2]")


class FakeSip:
    def __init__(self) -> None:
        self.requests: list[api.CreateSIPParticipantRequest] = []

    async def create_sip_participant(self, request):
        self.requests.append(request)


async def test_dialing_rings_the_number_and_waits_for_an_answer(monkeypatch):
    monkeypatch.setenv("SIP_OUTBOUND_TRUNK_ID", "ST_test")
    monkeypatch.setenv("SIP_FROM_NUMBER", "+919000000000")
    monkeypatch.delenv("RING_SECONDS", raising=False)
    sip = FakeSip()
    ctx = SimpleNamespace(room=SimpleNamespace(name="survey-5-abc"), api=SimpleNamespace(sip=sip))
    await dial(ctx, "+919876543210", max_call_seconds=240)
    (request,) = sip.requests
    assert (request.room_name, request.sip_trunk_id, request.sip_call_to) == (
        "survey-5-abc",
        "ST_test",
        "+919876543210",
    )
    assert request.participant_identity == CALLEE and request.wait_until_answered
    assert request.ringing_timeout.seconds == 35 and request.max_call_duration.seconds == 300
    assert request.sip_number == "+919000000000"


async def test_dialing_without_a_trunk_says_what_to_set(monkeypatch):
    monkeypatch.delenv("SIP_OUTBOUND_TRUNK_ID", raising=False)
    with pytest.raises(MissingTrunk, match="SIP_OUTBOUND_TRUNK_ID"):
        await dial(SimpleNamespace(), "+919876543210", max_call_seconds=240)


def sip_error(code: int, reason: str) -> api.SipCallError:
    return api.SipCallError(
        "unavailable", "sip failed", status=503, metadata={"sip_status_code": str(code), "sip_status": reason}
    )


@pytest.mark.parametrize(
    ("code", "status"),
    [(486, "busy"), (603, "busy"), (480, "no_answer"), (408, "no_answer"), (487, "no_answer"),
     (404, "failed"), (403, "failed"), (500, "failed")],
)  # fmt: skip
def test_a_failed_dial_is_written_down_for_what_it_was(code, status):
    found, note = outcome_of_failed_dial(sip_error(code, "reason"))
    assert found == status and str(code) in note


def test_other_dial_failures_are_failed():
    assert outcome_of_failed_dial(MissingTrunk("no trunk")) == ("failed", "no trunk")
    assert outcome_of_failed_dial(RuntimeError("boom"))[0] == "failed"


def test_each_call_gets_its_own_id():
    assert new_call_id() != new_call_id() and new_call_id().startswith("call_")
