"""Everything around the answers: silence, speech that never became words, the time limit, hanging up.

- Silence: when the person says nothing for a while, check in once ("હેલો? ... સંભળાય છે?"). If they
  stay silent, say goodbye and hang up.
- No words: the person spoke, but the speech-to-text sent nothing back. A short answer, such as a
  name, is the likeliest to get lost this way, and the agent used to sit in silence until the silence
  check-in, which sounded like it had stopped working. Now it asks again within a few seconds.
- Length: no call runs past MAX_CALL_SECONDS.
- Goodbye: once the survey's last line has played, hang up.

All of these say fixed lines, so they cost no LLM requests.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from livekit.agents import AgentSession, JobContext, UserStateChangedEvent
from livekit.agents.voice.events import UserTranscriptionTimeoutEvent
from livekit.agents.voice.speech_handle import SpeechHandle

from agent.survey.agent import SurveyAgent
from agent.survey.flow import Survey
from agent.survey.script import SILENCE_GOODBYE, TIME_UP

logger = logging.getLogger("agent.survey.controls")

# VAD speech shorter than this with no words is a cough or a click, not a lost answer.
MIN_LOST_SPEECH_SECONDS = 0.3
# Asking again for lost words this many times in a row, then waiting for the silence check-in: a
# line so noisy that nothing gets through shouldn't hear the question on a loop.
MAX_LOST_IN_A_ROW = 2
# After "એક મિનિટ" (hold on), silence lasts this many times longer before the agent gives up.
HOLD_ON_PATIENCE = 3


class CallControls:
    def __init__(
        self,
        session: AgentSession,
        ctx: JobContext,
        survey: Survey,
        agent: SurveyAgent,
        *,
        max_call_seconds: float,
        silence_grace_seconds: float = 8.0,
        on_hang_up: Callable[[str], None] = lambda _reason: None,
    ) -> None:
        self._session = session
        self._ctx = ctx
        self._survey = survey
        self._agent = agent
        self._max_call_seconds = max_call_seconds
        self._silence_grace_seconds = silence_grace_seconds
        self._on_hang_up = on_hang_up
        self._ending = False
        self._lost_in_a_row = 0
        self._timers: list[asyncio.Task[None]] = []
        self._silence: asyncio.Task[None] | None = None

    @property
    def ending(self) -> bool:
        return self._ending

    def start(self) -> None:
        self._session.on("user_state_changed", self._on_user_state)
        self._session.on("user_transcription_timeout", self._on_lost_words)
        self._session.on("user_input_transcribed", self._on_words)
        self._session.on("close", lambda _ev: self._cancel_timers())
        self._timers.append(asyncio.create_task(self._end_at_time_limit(), name="call_time_limit"))

    def stop(self) -> None:
        """The call is over: no check-ins or hang-ups from here on."""
        self._ending = True
        self._cancel_timers()

    def _on_user_state(self, ev: UserStateChangedEvent) -> None:
        if ev.new_state == "speaking" and self._silence:
            self._silence.cancel()  # they answered
            self._silence = None
        elif ev.new_state == "away" and not self._ending and not self._silence:
            # LiveKit reports "away" once and stays there, so the follow-up needs its own timer.
            self._silence = asyncio.create_task(self._check_in_then_hang_up(), name="silence_check_in")
            self._timers.append(self._silence)

    def _on_words(self, ev: object) -> None:
        if getattr(ev, "is_final", False) and getattr(ev, "transcript", "").strip():
            self._lost_in_a_row = 0

    def _on_lost_words(self, ev: UserTranscriptionTimeoutEvent) -> None:
        if (
            self._ending
            or self._survey.finished
            or ev.speech_duration < MIN_LOST_SPEECH_SECONDS
            or self._agent.heard_too_early(ev.vad_speech_started_at)
            or self._session.agent_state not in ("listening", "idle")
            or self._lost_in_a_row >= MAX_LOST_IN_A_ROW
        ):
            return
        self._lost_in_a_row += 1
        line = self._survey.didnt_hear()
        logger.info("speech with no words (%.1f s): asking again", ev.speech_duration)
        self._session.say(line)

    async def _check_in_then_hang_up(self) -> None:
        if self._survey.waiting:  # "એક મિનિટ": they may have gone to ask someone
            await asyncio.sleep(self._silence_grace_seconds * (HOLD_ON_PATIENCE - 1))
        await self._session.say(self._survey.check_in())
        await asyncio.sleep(self._silence_grace_seconds * (HOLD_ON_PATIENCE if self._survey.waiting else 1))
        await self.hang_up(SILENCE_GOODBYE, reason="no answer")

    async def _end_at_time_limit(self) -> None:
        await asyncio.sleep(self._max_call_seconds)
        await self.hang_up(TIME_UP, reason="max call length reached")

    async def hang_up(self, goodbye: str, *, reason: str) -> None:
        """Say a fixed goodbye, then end the call."""
        if self._ending:
            return
        self._ending = True
        self._survey.end()
        try:
            await self._session.interrupt(force=True)
            await self._session.say(goodbye, allow_interruptions=False)
        finally:
            await self._disconnect(reason)

    def end_after(self, speech: SpeechHandle) -> None:
        """Hang up once `speech` (the survey's last line) has played."""
        if self._ending:
            return
        self._ending = True

        def done(_handle: SpeechHandle) -> None:
            self._timers.append(asyncio.create_task(self._disconnect("survey finished")))

        speech.add_done_callback(done)

    async def _disconnect(self, reason: str) -> None:
        logger.info("hanging up: %s", reason)
        self._on_hang_up(reason)
        self._cancel_timers()
        self._session.shutdown()
        await self._ctx.delete_room()  # hangs up the phone too; a no-op in console mode
        self._ctx.shutdown(reason=reason)

    def _cancel_timers(self) -> None:
        current = asyncio.current_task()
        for task in self._timers:
            if task is not current:
                task.cancel()
