"""The survey agent: on each turn, read what the person said and say the survey's next line.

This replaces the LLM's free reply with the survey (llm_node): the LLM reads the answer, the flow
picks the line, and nothing else is ever said. That is what keeps the call on track after an
answer, where the old receptionist relied on the LLM to call the right tool next and sometimes didn't.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable

from livekit.agents import Agent, ModelSettings, StopResponse, llm
from livekit.agents.voice.speech_handle import SpeechHandle

from agent.phone import masked
from agent.survey.flow import Reply, Survey
from agent.survey.reader import AnswerReader

logger = logging.getLogger("agent.survey")

INSTRUCTIONS = "You run a phone survey in Gujarati. Every line you say comes from the survey script."


class SurveyAgent(Agent):
    def __init__(
        self,
        survey: Survey,
        reader: AnswerReader,
        *,
        on_reply: Callable[[Reply], None] = lambda _reply: None,
        on_goodbye: Callable[[SpeechHandle], None] = lambda _speech: None,
        phone: str | None = None,
    ) -> None:
        super().__init__(instructions=INSTRUCTIONS)
        self._survey = survey
        self._reader = reader
        self._on_reply = on_reply
        self._on_goodbye = on_goodbye
        self._phone = phone
        self._listening_since: float | None = None  # when the introduction finished playing

    @property
    def listening_since(self) -> float | None:
        return self._listening_since

    def start_listening(self) -> None:
        """The introduction has played: from now on, what the person says is an answer."""
        self._listening_since = time.time()

    def heard_too_early(self, started_speaking_at: float | None) -> bool:
        """Speech that began before the introduction ended: a "હેલો?" over it, whose audio wasn't heard
        anyway (the introduction can't be interrupted). The question that follows answers it."""
        if self._listening_since is None:
            return True
        return started_speaking_at is not None and started_speaking_at < self._listening_since

    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        if self._survey.finished or self.heard_too_early(
            (new_message.metrics or {}).get("started_speaking_at")
        ):
            raise StopResponse()

    async def llm_node(
        self, chat_ctx: llm.ChatContext, tools: list[llm.Tool], model_settings: ModelSettings
    ) -> AsyncIterator[str]:
        """Read the turn, then say the survey's line for it. Runs once per finished turn: preemptive
        generation is off (main.py), as a guess at an unfinished turn would move the survey on."""
        survey = self._survey
        said = words_since_agent_spoke(chat_ctx)
        if survey.finished or not said:
            return
        asked = survey.asked
        reading = await self._reader.read(survey, said, last_line=last_agent_line(chat_ctx))
        reply = survey.respond(reading)
        logger.info(
            "survey | %s | asked %s | %s (%s) %s",
            masked(self._phone),
            asked,
            reading.intent,
            reading.source,
            reading.values,
        )
        self._on_reply(reply)
        if reply.end and reply.line:
            # Said by the session, not as this reply: a goodbye that can't be cut off, so the person
            # hears all of it, and the call hangs up once it has played.
            self._on_goodbye(self.session.say(reply.line, allow_interruptions=False))
            return
        if reply.line:
            yield reply.line


def words_since_agent_spoke(chat_ctx: llm.ChatContext) -> str:
    """Everything the person said since the agent's last line: one turn, or a turn and its sequel
    ("રમેશ" ... "પટેલ") when they paused long enough for the first part to end a turn."""
    parts: list[str] = []
    for item in reversed(chat_ctx.items):
        if item.type != "message":
            continue
        if item.role == "assistant":
            break
        if item.role == "user":
            parts.append(item.text_content or "")
    return " ".join(p.strip() for p in reversed(parts) if p.strip())


def last_agent_line(chat_ctx: llm.ChatContext) -> str:
    for item in reversed(chat_ctx.items):
        if item.type == "message" and item.role == "assistant":
            return item.text_content or ""
    return ""
