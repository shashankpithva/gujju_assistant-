"""Turn-taking tuned to what the agent just asked.

Callers pause while reading out a phone number ("98765 ... 43210"), and while they think of a name,
a day or how many are coming ("It's... Priyanka"). After the agent asks for one of those, the
session waits longer before deciding the caller has finished, longest for a number; once the caller
has answered, it goes back to the quick default, so every other reply stays fast.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from livekit.agents import AgentSession, ConversationItemAddedEvent, EndpointingOptions
from livekit.agents.llm import ChatMessage

from agent.gujarati.numbers import spoken_number_text

logger = logging.getLogger("agent.turn_taking")

# Seconds of silence after the caller's last word before their turn can end, and the most the
# agent waits when the turn detector thinks they haven't finished.
QUICK = EndpointingOptions(min_delay=0.3, max_delay=2.5)
TAKING_DETAIL = EndpointingOptions(min_delay=0.6, max_delay=3.0)
TAKING_DIGITS = EndpointingOptions(min_delay=1.0, max_delay=4.0)


@dataclass(frozen=True)
class Pauses:
    quick: EndpointingOptions
    detail: EndpointingOptions
    digits: EndpointingOptions


ENGLISH = Pauses(QUICK, TAKING_DETAIL, TAKING_DIGITS)
# LiveKit's turn detector wasn't trained on Gujarati (it runs on Hindi's threshold, see languages.py),
# so it can't be trusted to hold the turn while a caller thinks. A longer floor does that instead,
# at the cost of 0.2 s on each reply. Numbers get read more slowly too: "નવ આઠ... સાત છ".
GUJARATI = Pauses(
    EndpointingOptions(min_delay=0.5, max_delay=2.5),
    EndpointingOptions(min_delay=0.8, max_delay=3.0),
    EndpointingOptions(min_delay=1.2, max_delay=4.0),
)

_ASKS_FOR_NUMBER = re.compile(r"\b(phone )?number\b|નંબર", re.IGNORECASE)
# The booking details prepare_booking asks for (tools.ASK), and the same questions in the LLM's words.
_ASKS_FOR_DETAIL = re.compile(
    r"\b(name|booking under|how many|which day|what day|what date|which date|what time|day and time"
    r"|when would)\b|નામ|કેટલા લોકો|કેટલા જણ|કેટલા વાગ્યે|કયા દિવસે|કયો દિવસ|ક્યારે",
    re.IGNORECASE,
)
_HAS_DIGITS = re.compile(r"\d(?:\D?\d){4}")  # a read-back already holds the number
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


def _question(agent_text: str) -> str:
    """The last sentence, which is the question: "I only caught 1 2 3. Could you say it again?"."""
    return _SENTENCE_END.split(agent_text.strip())[-1]


def asks_for_a_number(agent_text: str) -> bool:
    # "Could you say the whole number again?" asks for one; "...your number is 9 8 7 6 5, 4 3 2 1 0.
    # Shall I book it?" doesn't.
    question = _question(agent_text)
    return bool(_ASKS_FOR_NUMBER.search(question)) and not _HAS_DIGITS.search(spoken_number_text(question))


def asks_for_a_detail(agent_text: str) -> bool:
    """A name, a day or time, or how many people: answers callers often pause in the middle of."""
    return bool(_ASKS_FOR_DETAIL.search(_question(agent_text)))


def endpointing_after(agent_text: str, pauses: Pauses = ENGLISH) -> EndpointingOptions:
    if asks_for_a_number(agent_text):
        return pauses.digits
    return pauses.detail if asks_for_a_detail(agent_text) else pauses.quick


class TurnTaking:
    def __init__(self, session: AgentSession, pauses: Pauses = ENGLISH) -> None:
        self._session = session
        self._pauses = pauses
        self._current = pauses.quick

    def attach(self) -> None:
        self._session.on("conversation_item_added", self._on_item_added)

    def _on_item_added(self, ev: ConversationItemAddedEvent) -> None:
        item = ev.item
        if not isinstance(item, ChatMessage):
            return
        if item.role == "assistant":
            self._use(endpointing_after(item.text_content or "", self._pauses))
        elif item.role == "user":
            self._use(self._pauses.quick)

    def _use(self, options: EndpointingOptions) -> None:
        if options != self._current:
            self._session.update_options(endpointing_opts=options)
            self._current = options
            logger.debug("endpointing now %s", options)
