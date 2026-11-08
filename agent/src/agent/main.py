"""Entrypoint: one survey call per LiveKit job, dialed out to a number from the sheet.

Run from agent/:
    uv run python -m agent.main download-files   # once: turn detector and VAD weights
    uv run python -m agent.main console          # a test call in this terminal, with your mic
    uv run python -m agent.main dev              # serve calls; then `uv run python -m agent.dialer run`

A call goes: dial and wait for an answer, let the person say "હેલો?", introduce the survey, ask the
seven questions (survey/), write each answer into the sheet as it comes, say thank you, hang up.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    TurnHandlingOptions,
    cli,
    room_io,
)
from livekit.plugins import noise_cancellation, silero

from agent.gujarati.speech import Gender
from agent.languages import (
    Hearing,
    build_hearing,
    build_turn_detection,
    build_voice,
    voice_gender,
    voice_text_transforms,
)
from agent.llm_setup import build_llm
from agent.metrics import LatencyTracker, Turn
from agent.outbound import CALLEE, CallRequest, dial, new_call_id, outcome_of_failed_dial
from agent.phone import masked
from agent.settings import agent_name, seconds, stamp
from agent.sheets import ANSWER_KEYS, CALLING, ContactSheet, open_sheet
from agent.survey.agent import SurveyAgent
from agent.survey.controls import CallControls
from agent.survey.flow import Reply, Survey
from agent.survey.reader import AnswerReader
from agent.survey.recorder import SheetRecorder
from agent.survey.script import Script

if TYPE_CHECKING:
    from livekit.agents.voice.room_io.types import NoiseCancellationParams

load_dotenv()
logger = logging.getLogger("agent")
_background_tasks: set[asyncio.Task[None]] = set()

# After the call is answered the person is already in the room: this only runs out if they're gone.
PARTICIPANT_WAIT_SECONDS = 10.0


def select_noise_cancellation(params: NoiseCancellationParams):
    """Phone audio gets the telephony-tuned model; browser and console audio get the general one."""
    if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
        return noise_cancellation.BVCTelephony()
    return noise_cancellation.BVC()


def transcript(turns: list[Turn]) -> str:
    """The conversation, for the sheet's Transcript column."""
    lines = (
        f"{'AI' if t.speaker == 'agent' else 'Person'}: {t.text.strip()}" for t in turns if t.text.strip()
    )
    return "\n".join(lines)


async def wait_for_hello(
    session: AgentSession, *, first_words_within: float, longest_hello: float = 3.0
) -> None:
    """People answer the phone with "હેલો?" before they listen. Let them say it, then begin; begin
    anyway if they say nothing."""
    if first_words_within <= 0:
        return
    started, finished = asyncio.Event(), asyncio.Event()

    def on_state(ev: Any) -> None:
        if ev.new_state == "speaking":
            started.set()
            finished.clear()
        elif started.is_set():
            finished.set()

    session.on("user_state_changed", on_state)
    try:
        if session.user_state == "speaking":
            started.set()
        try:
            await asyncio.wait_for(started.wait(), first_words_within)
        except TimeoutError:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(finished.wait(), longest_hello)
    finally:
        session.off("user_state_changed", on_state)


async def release_console_audio() -> None:
    """Console mode: close the terminal's microphone and speaker before the job's event loop closes.

    LiveKit's console (livekit-agents 1.8) leaves both running when a call ends, and every audio
    callback then fails with "Event loop is closed", which Windows shows as one error dialog after
    another.
    """
    console = cli.AgentsConsole.get_instance()
    for name in ("set_microphone_enabled", "set_speaker_enabled"):
        if set_enabled := getattr(console, name, None):
            set_enabled(False)


def build_session(
    *,
    vad: Any,
    hearing: Hearing,
    model: Any,
    voice: Any,
    turn_detection: Any,
    gender: Gender,
    silence_seconds: float,
) -> AgentSession:
    """The voice pipeline for one call, tuned for a survey's short answers."""
    return AgentSession(
        vad=vad,
        stt=hearing.stt,
        llm=model,
        tts=voice,
        turn_handling=TurnHandlingOptions(
            turn_detection=turn_detection,
            # Answers are short: a name, a place, "હા". A floor long enough for "અમારું ગામ... ખાંભા",
            # and a cap so a bare answer never hangs for long when the turn detector is unsure.
            endpointing={
                "min_delay": seconds("ENDPOINTING_MIN_DELAY", 0.7),
                "max_delay": seconds("ENDPOINTING_MAX_DELAY", 2.0),
            },
            # Off: each reply moves the survey on, and a guess at an unfinished turn would move it too.
            preemptive_generation={"enabled": False},
            interruption=hearing.interruption,
        ),
        tts_text_transforms=voice_text_transforms(gender),
        user_away_timeout=silence_seconds,
        # Speech that brings no words for this long gets the question again (survey/controls.py).
        transcription_timeout=seconds("TRANSCRIPTION_TIMEOUT_SECONDS", 3.0),
    )


def room_options(*, outbound: bool) -> room_io.RoomOptions:
    """Listen to the person called (not anyone else who joins), through noise cancellation."""
    options: dict[str, Any] = {}
    if os.getenv("NOISE_CANCELLATION", "on").lower() != "off":
        options["audio_input"] = room_io.AudioInputOptions(noise_cancellation=select_noise_cancellation)
    if outbound:
        options["participant_identity"] = CALLEE
    return room_io.RoomOptions(**options)


def prewarm(proc: JobProcess) -> None:
    # Loaded once per worker process, not once per call. End-of-turn detection starts only after this
    # much silence; the turn detector decides whether the person has actually finished.
    proc.userdata["vad"] = silero.VAD.load(min_silence_duration=seconds("VAD_MIN_SILENCE_SECONDS", 0.3))


server = AgentServer(setup_fnc=prewarm)


@dataclass
class Outcome:
    """How a call ended that never reached the survey: busy, no answer, a setup problem."""

    status: str
    note: str


def _spawn(coro: Any) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@server.rtc_session(agent_name=agent_name())
async def entrypoint(ctx: JobContext) -> None:
    call_id = new_call_id()
    ctx.log_context_fields = {"room": ctx.room.name, "call_id": call_id}
    started_at = datetime.now(UTC)
    if ctx.is_fake_job():
        ctx.add_shutdown_callback(release_console_audio)

    try:
        request = CallRequest.from_metadata(None if ctx.is_fake_job() else ctx.job.metadata)
    except ValueError as e:
        logger.error("can't place this call, the job's metadata is wrong: %s", e)
        ctx.shutdown(reason="bad metadata")
        return

    sheet: ContactSheet | None = None
    try:
        sheet = open_sheet(request.sheet)
    except Exception as e:
        logger.error("the sheet can't be opened, so answers won't be saved: %s", e)
    if sheet is None:
        logger.warning("no sheet (set GOOGLE_SHEET_ID or SURVEY_CSV): answers will only be in the log")
    recorder = SheetRecorder(sheet, request.row, phone=request.phone)
    call_stamp = {"call_id": call_id, "last_call": stamp(started_at)}
    max_call_seconds = seconds("MAX_CALL_SECONDS", 240)

    survey = Survey(Script.from_env())
    try:
        session_llm, llm_label = build_llm()
        hearing = build_hearing("phone" if request.outbound else "browser")
        voice, gender, turn_detection = build_voice(), voice_gender(), build_turn_detection()
    except Exception as e:  # a missing key or a bad setting: don't ring anyone's phone for nothing
        logger.error("the agent isn't set up to talk: %s", e)
        await recorder.close({"status": "failed", "notes": f"Agent setup: {e}", **call_stamp})
        ctx.shutdown(reason="setup failed")
        return

    silence_seconds = seconds("SILENCE_CHECK_IN_SECONDS", 8)
    session = build_session(
        vad=ctx.proc.userdata["vad"],
        hearing=hearing,
        model=session_llm,
        voice=voice,
        turn_detection=turn_detection,
        gender=gender,
        silence_seconds=silence_seconds,
    )
    latency = LatencyTracker(llm_model=llm_label)
    latency.attach(session)

    def on_reply(reply: Reply) -> None:
        if reply.changed or reply.end:  # the sheet fills in as the person answers
            recorder.write({**survey.sheet_values(), **({"status": survey.status} if survey.status else {})})

    agent = SurveyAgent(
        survey,
        AnswerReader(session_llm),
        on_reply=on_reply,
        on_goodbye=lambda speech: controls.end_after(speech),
        phone=request.phone,
    )
    controls = CallControls(
        session, ctx, survey, agent, max_call_seconds=max_call_seconds, silence_grace_seconds=silence_seconds
    )
    outcome: Outcome | None = None
    closing: asyncio.Task[None] | None = None

    async def close_call() -> None:
        """Once per call, however it ended: the result goes to the sheet. Everyone who asks waits
        for the same write, so the job can't end while the last answers are still on their way."""
        nonlocal closing
        if closing is None:
            closing = asyncio.create_task(save_result())
        await asyncio.shield(closing)

    async def save_result() -> None:
        controls.stop()
        latency.log_summary()
        for usage in session.usage.model_usage:
            if getattr(usage, "type", "") == "llm_usage":
                logger.info(
                    "llm usage | %s %s | input %d tokens, output %d tokens",
                    usage.provider,
                    usage.model,
                    usage.input_tokens,
                    usage.output_tokens,
                )
        if outcome is not None:
            final = {"status": outcome.status, "notes": outcome.note, **call_stamp}
        else:
            final = {
                **survey.sheet_values(),
                "status": survey.end(),
                "notes": survey.note(),
                "transcript": transcript(latency.turns),
                **call_stamp,
            }
        logger.info(
            "call ended | %s | %s | %s", masked(request.phone), final["status"], final["notes"] or "-"
        )
        await recorder.close(final)

    ctx.add_shutdown_callback(close_call)

    async def finish(reason: str) -> None:
        await close_call()
        with contextlib.suppress(Exception):
            await ctx.delete_room()  # hangs up, and tells the dialer the call is over
        ctx.shutdown(reason=reason)

    # Started before dialing, so it's listening the moment the person picks up.
    session_started = asyncio.create_task(
        session.start(agent=agent, room=ctx.room, room_options=room_options(outbound=request.outbound))
    )

    if request.phone:
        logger.info("calling %s | row %s | attempt %d", masked(request.phone), request.row, request.attempt)
        try:
            await dial(ctx, request.phone, max_call_seconds=max_call_seconds)
        except Exception as e:
            outcome = Outcome(*outcome_of_failed_dial(e))
            logger.info("the call didn't connect: %s", outcome.note)
            with contextlib.suppress(Exception):
                await session_started
            await finish(outcome.status)
            return
        await session_started
        try:  # already in the room; gone only if they hung up the moment they answered
            await asyncio.wait_for(ctx.wait_for_participant(identity=CALLEE), PARTICIPANT_WAIT_SECONDS)
        except TimeoutError:
            logger.info("the person hung up as soon as they answered")
            await finish("hung up at once")
            return
        hello_wait = seconds("HELLO_WAIT_SECONDS", 2.0)
    else:
        await session_started
        if not ctx.is_fake_job():
            await ctx.wait_for_participant()
        hello_wait = 0.5
    session.on("close", lambda _ev: _spawn(finish("call closed")))

    # A clean row for this call: no answers left over from an earlier attempt.
    recorder.write({**dict.fromkeys(ANSWER_KEYS, ""), "status": CALLING, "notes": "", **call_stamp})
    logger.info("call connected | %s | %s", masked(request.phone), call_id)

    await wait_for_hello(session, first_words_within=hello_wait)
    if closing is not None:  # they hung up while saying hello
        return
    intro, first_question = survey.opening()
    # The introduction can't be cut off: a "હેલો? હેલો?" over it would otherwise stop it halfway. The
    # question after it can, by someone answering straight away.
    introduction = session.say(intro, allow_interruptions=False)
    introduction.add_done_callback(lambda _speech: agent.start_listening())
    session.say(first_question)
    controls.start()


if __name__ == "__main__":
    cli.run_app(server)
