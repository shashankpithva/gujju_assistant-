"""Silence, lost words, the time limit and hanging up: the call never just sits there."""

import asyncio
import time
from types import SimpleNamespace

from livekit.agents import UserStateChangedEvent
from livekit.agents.voice.events import UserTranscriptionTimeoutEvent

from agent.survey.agent import SurveyAgent
from agent.survey.controls import MAX_LOST_IN_A_ROW, CallControls
from agent.survey.flow import Survey
from agent.survey.reader import AnswerReader
from agent.survey.script import CHECK_IN, QUESTIONS, SILENCE_GOODBYE, TIME_UP
from tests.conftest import FakeJob, FakeSession, Speech


def call(**limits) -> tuple[CallControls, FakeSession, FakeJob, Survey, SurveyAgent]:
    session, job, survey = FakeSession(), FakeJob(), Survey()
    survey.opening()
    agent = SurveyAgent(survey, AnswerReader(None))
    agent.start_listening()
    controls = CallControls(session, job, survey, agent, **{"max_call_seconds": 60, **limits})
    controls.start()
    return controls, session, job, survey, agent


def state(new: str) -> UserStateChangedEvent:
    return UserStateChangedEvent(old_state="listening", new_state=new)


def lost(seconds: float = 0.8, started: float | None = None) -> UserTranscriptionTimeoutEvent:
    return UserTranscriptionTimeoutEvent(
        speech_duration=seconds, vad_speech_started_at=started if started is not None else time.time()
    )


async def test_speech_with_no_words_gets_the_question_again_within_seconds():
    # The reported stall: a short answer like a name came through as speech but no words, and the
    # agent said nothing until the silence check-in. Now it asks again.
    _, session, _, survey, _ = call()
    session.emit("user_transcription_timeout", lost())
    assert session.said == [QUESTIONS["name"].again]
    assert survey.asked == "name"


async def test_lost_words_are_ignored_when_they_shouldnt_get_a_reply():
    _, session, _, _, agent = call()
    session.emit("user_transcription_timeout", lost(seconds=0.1))  # a cough
    session.emit("user_transcription_timeout", lost(started=agent.listening_since - 5))  # over the intro
    session.agent_state = "speaking"
    session.emit("user_transcription_timeout", lost())  # the agent is already talking
    assert session.said == []


async def test_lost_words_dont_get_the_question_on_a_loop():
    _, session, _, _, _ = call()
    for _ in range(MAX_LOST_IN_A_ROW + 2):
        session.emit("user_transcription_timeout", lost())
    assert len(session.said) == MAX_LOST_IN_A_ROW
    session.emit("user_input_transcribed", SimpleNamespace(is_final=True, transcript="રમેશ"))
    session.emit("user_transcription_timeout", lost())  # words got through in between: ask again
    assert len(session.said) == MAX_LOST_IN_A_ROW + 1


async def test_silence_gets_one_check_in_then_a_goodbye_and_hang_up():
    _, session, job, survey, _ = call(silence_grace_seconds=0.01)
    session.emit("user_state_changed", state("away"))
    await asyncio.sleep(0.05)
    assert session.said == [CHECK_IN, SILENCE_GOODBYE]
    assert session.shut_down and job.room_deleted and job.shutdown_reason == "no answer"
    assert survey.status == "no_answer"


async def test_answering_the_check_in_keeps_the_call_going():
    _, session, _, _, _ = call(silence_grace_seconds=0.05)
    session.emit("user_state_changed", state("away"))
    await asyncio.sleep(0.01)
    session.emit("user_state_changed", state("speaking"))
    await asyncio.sleep(0.1)
    assert session.said == [CHECK_IN] and not session.shut_down


async def test_calls_are_wrapped_up_at_the_time_limit():
    _, session, job, survey, _ = call(max_call_seconds=0.01)
    await asyncio.sleep(0.05)
    assert session.said == [TIME_UP] and job.shutdown_reason == "max call length reached"
    assert survey.finished


async def test_hang_up_happens_once():
    controls, session, _, _, _ = call()
    await controls.hang_up("આવજો!", reason="test")
    await controls.hang_up("ફરી આવજો!", reason="test")
    assert session.said == ["આવજો!"]


async def test_the_call_hangs_up_once_the_goodbye_has_played():
    controls, session, job, _, _ = call()
    goodbye = Speech("આવજો!")
    controls.end_after(goodbye)
    await asyncio.sleep(0)
    assert not session.shut_down  # still saying it
    goodbye.finish()
    await asyncio.sleep(0.01)
    assert session.shut_down and job.room_deleted and job.shutdown_reason == "survey finished"
    session.emit("user_state_changed", state("away"))  # no check-ins once hanging up
    assert session.said == []


async def test_nothing_fires_once_the_call_is_over():
    controls, session, job, _, _ = call(max_call_seconds=0.05, silence_grace_seconds=0.01)
    controls.stop()
    session.emit("user_state_changed", state("away"))
    session.emit("user_transcription_timeout", lost())
    await asyncio.sleep(0.1)
    assert session.said == [] and not job.room_deleted


async def test_after_hold_on_the_agent_waits_longer_before_giving_up():
    from agent.survey.flow import Reading

    _, session, job, survey, _ = call(silence_grace_seconds=0.02)
    survey.respond(Reading("wait"))  # "એક મિનિટ"
    session.emit("user_state_changed", state("away"))
    await asyncio.sleep(0.03)
    assert session.said == []  # a normal call would have checked in by now
    await asyncio.sleep(0.2)
    assert session.said == [CHECK_IN, SILENCE_GOODBYE] and job.room_deleted
