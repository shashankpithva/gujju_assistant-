"""The call's start and end: waiting for "હેલો?", and the transcript for the sheet."""

import asyncio
from datetime import UTC, datetime

from livekit.agents import UserStateChangedEvent

from agent.main import transcript, wait_for_hello
from agent.metrics import Turn
from tests.conftest import FakeSession


def state(new: str) -> UserStateChangedEvent:
    return UserStateChangedEvent(old_state="listening", new_state=new)


async def test_the_agent_waits_for_hello_then_begins():
    session = FakeSession()
    waiting = asyncio.create_task(wait_for_hello(session, first_words_within=1.0))
    await asyncio.sleep(0.01)
    session.emit("user_state_changed", state("speaking"))  # "હેલો?"
    await asyncio.sleep(0.01)
    assert not waiting.done()  # still saying it
    session.emit("user_state_changed", state("listening"))
    await asyncio.wait_for(waiting, 0.5)
    assert session.handlers["user_state_changed"] == []  # cleaned up


async def test_a_silent_pick_up_gets_the_introduction_anyway():
    session = FakeSession()
    started = asyncio.get_running_loop().time()
    await wait_for_hello(session, first_words_within=0.05)
    assert asyncio.get_running_loop().time() - started < 0.5


async def test_a_long_hello_doesnt_hold_the_call_up():
    session = FakeSession()
    session.user_state = "speaking"
    await asyncio.wait_for(wait_for_hello(session, first_words_within=1.0, longest_hello=0.05), 0.5)


def test_the_transcript_reads_as_a_conversation():
    at = datetime(2026, 11, 8, tzinfo=UTC)
    turns = [
        Turn(0, "agent", "તમારું નામ શું છે?", at, False),
        Turn(1, "caller", "રમેશ", at, False),
        Turn(2, "caller", "  ", at, False),
    ]
    assert transcript(turns) == "AI: તમારું નામ શું છે?\nPerson: રમેશ"


async def test_the_session_is_built_with_the_surveys_settings(monkeypatch):
    from livekit.plugins import silero

    from agent.languages import build_hearing, build_turn_detection, build_voice
    from agent.llm_setup import build_llm
    from agent.main import build_session, room_options
    from agent.outbound import CALLEE

    for name in ("SARVAM_API_KEY", "GROQ_API_KEY", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.setenv(name, "test")
    monkeypatch.setenv("LIVEKIT_URL", "wss://test.livekit.cloud")
    model, _ = build_llm()
    session = build_session(
        vad=silero.VAD.load(),
        hearing=build_hearing("phone"),
        model=model,
        voice=build_voice(),
        turn_detection=build_turn_detection(),
        gender="male",
        silence_seconds=8,
    )
    options = session.options
    assert options.preemptive_generation["enabled"] is False  # a guess must never move the survey on
    assert options.endpointing["min_delay"] == 0.7 and options.endpointing["max_delay"] == 2.0
    assert options.interruption["min_words"] == 0  # Sarvam sends finished sentences only
    assert options.transcription_timeout == 3.0 and options.user_away_timeout == 8
    assert room_options(outbound=True).participant_identity == CALLEE
