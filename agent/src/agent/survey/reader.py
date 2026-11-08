"""Reading one caller turn: which answers it holds, and what else it means (busy, "who is this?").

The LLM's only job on a call is this reading. It's asked one small, fixed question per turn and must
answer with the record_answer function, so it can't wander off-script or say anything itself. What
the caller hears next is decided by flow.py from the reading.

Three ways to read a turn, in order:
1. Rules, for short answers they understand completely ("હા", "રોજ", "અડધો કલાક"): no LLM request,
   so about a second sooner, and one request fewer against the free tier's limits.
2. The LLM, for everything else: names, places, dialect, several answers at once, corrections.
3. Rules again, best effort, when the LLM fails or is too slow, so the call never stalls.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from livekit.agents import llm

from agent.survey.answers import (
    asks_to_repeat,
    clean_days,
    clean_minutes,
    clean_note,
    clean_text,
    days_from,
    is_busy,
    minutes_from,
    says_goodbye,
    yes_or_no,
)
from agent.survey.flow import INTENTS, TEXT_FIELDS, Reading, Survey
from agent.survey.script import FIELDS, QUESTIONS

logger = logging.getLogger("agent.survey.reader")

# The most a turn waits for the LLM before the rules answer instead. Groq answers in well under a
# second; this is for a provider that hangs.
READ_TIMEOUT_SECONDS = 5.0

INSTRUCTIONS = """\
You read one turn of a phone survey in Gujarat and record it with the record_answer function. Always call it, exactly once.

The survey asks these, in this order:
- name: the person's name.
- village: their village or town (ગામ).
- taluka: their taluka (તાલુકો).
- district: their district (જિલ્લો).
- water_supply: does water come to them? yes or no.
- frequency_days: every how many days water comes. 1 = every day (રોજ), 2 = alternate days (એકાંતરે), 3 = every third day, 7 = once a week, 3.5 = twice a week.
- duration_minutes: on a day it comes, how long water runs, in minutes. અડધો કલાક = 30, પોણો કલાક = 45, એક કલાક = 60, દોઢ કલાક = 90, અઢી કલાક = 150. A time range: "સવારે 6 થી 8" = 120.

The words come from speech recognition: expect Gujarati, Hindi or English words in either script, Kathiawadi, Surti or other local speech, and recognition mistakes.

Rules:
- Record only what the person actually said. Never guess, and never fill a field from general knowledge (don't add a district because you know where a village is).
- They usually answer the question just asked, but may answer several at once, or correct an earlier answer ("ના, ગામ ખાંભા છે"): record those too.
- Write names and places in Gujarati script, spelled as commonly written ("ભાવનગર", "રાજકોટ"), without filler such as "મારું નામ", "ગામ" or "છે". Keep ભાઈ or બેન if they said it.
- When how often or how long isn't a plain number ("ક્યારેક", "નક્કી નહીં"), put their words in frequency_note or duration_note.
- "એક મિનિટ" or "બે મિનિટ" on its own usually means "hold on" (intent wait), not a duration.
- When the agent's last words weren't the question (for example "હેલો, તમને મારો અવાજ સંભળાય છે?"), a bare "હા" answers those words: intent acknowledge, not an answer to the question.

intent:
- answer: they answered at least one question.
- unclear: you can't tell what they said, or it doesn't answer the question.
- repeat: they ask to hear the question again ("શું?", "ફરીથી બોલો").
- question: they ask something back. Set asked_about: who (who is calling), why (why these questions) or other.
- acknowledge: only "હા", "બોલો", "ઠીક છે" or similar, to a question that isn't yes or no.
- wait: they ask you to hold on ("એક મિનિટ", "ઊભા રહો").
- busy: they're busy now, or ask for a call later.
- refuse: they don't want to take part.
- goodbye: they want to end the call now.

Examples (question asked: what they said -> what to record):
- name: "હા બોલો" -> intent acknowledge
- name: "મારું નામ રમેશભાઈ પટેલ" -> answer, name "રમેશભાઈ પટેલ"
- name: "Ramesh" -> answer, name "રમેશ"
- village: "ખાંભા, તાલુકો ખાંભા ને જિલ્લો અમરેલી" -> answer, village "ખાંભા", taluka "ખાંભા", district "અમરેલી"
- taluka: "ના ના, ગામ ખાંભા નહીં, ખંભાળિયા" -> answer, village "ખંભાળિયા"
- water_supply: "હા, આવે છે ને રોજ સવારે" -> answer, water_supply yes, frequency_days 1
- water_supply: "ક્યારેક આવે, ક્યારેક નહીં" -> answer, water_supply yes, frequency_note "ક્યારેક આવે, ક્યારેક નહીં"
- frequency_days: "ત્રણ દિવસે એક વાર" -> answer, frequency_days 3
- duration_minutes: "માંડ અડધો કલાક" -> answer, duration_minutes 30
- duration_minutes: "એક મિનિટ, બા ને પૂછું" -> intent wait
- any question: "અત્યારે ટાઈમ નથી, પછી ફોન કરજો" -> intent busy
- any question: "તમે કોણ બોલો છો?" -> intent question, asked_about who
"""

RECORD_ANSWER = {
    "name": "record_answer",
    "description": "Record what the person said in this turn of the survey.",
    "parameters": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": list(INTENTS)},
            "asked_about": {
                "type": "string",
                "enum": ["who", "why", "other"],
                "description": "Only for intent question.",
            },
            "name": {"type": "string", "description": "The person's name, in Gujarati script."},
            "village": {"type": "string", "description": "Their village or town, in Gujarati script."},
            "taluka": {"type": "string", "description": "Their taluka, in Gujarati script."},
            "district": {"type": "string", "description": "Their district, in Gujarati script."},
            "water_supply": {"type": "string", "enum": ["yes", "no"], "description": "Does water come?"},
            "frequency_days": {"type": "number", "description": "Every how many days water comes."},
            "frequency_note": {"type": "string", "description": "Their words, if not a number of days."},
            "duration_minutes": {"type": "number", "description": "Minutes water runs on a day it comes."},
            "duration_note": {"type": "string", "description": "Their words, if not a length of time."},
        },
        "required": ["intent"],
    },
}

# The field names the LLM sees for each question: the same names as the function's arguments.
_FIELD_KEY = {"frequency": "frequency_days", "duration": "duration_minutes"}


@llm.function_tool(raw_schema=RECORD_ANSWER)
async def record_answer(raw_arguments: dict[str, object]) -> None:
    """Never run: the reader takes the call's arguments straight from the LLM's reply."""


class AnswerReader:
    def __init__(self, model: llm.LLM | None, *, timeout: float = READ_TIMEOUT_SECONDS) -> None:
        self._llm = model
        self._timeout = timeout

    async def read(self, survey: Survey, said: str, *, last_line: str = "") -> Reading:
        """What `said` (everything the caller said since the agent last spoke) means for the survey."""
        current = survey.asked or FIELDS[0]
        asked = asked_just_now(current, last_line)
        if asked and (quick := quick_reading(current, said)) is not None:
            return quick
        if self._llm is not None:
            try:
                return await asyncio.wait_for(self._ask_llm(survey, said, last_line), self._timeout)
            except Exception as e:  # any failure: the rules below keep the call going
                logger.warning("the LLM couldn't read the answer, using the rules instead: %r", e)
        return fallback_reading(current, said, asked=asked)

    async def _ask_llm(self, survey: Survey, said: str, last_line: str) -> Reading:
        ctx = llm.ChatContext()
        ctx.add_message(role="system", content=INSTRUCTIONS)
        ctx.add_message(role="user", content=describe_turn(survey, said, last_line))
        arguments: str | None = None
        async with self._llm.chat(chat_ctx=ctx, tools=[record_answer], tool_choice="required") as stream:  # type: ignore[union-attr]
            async for chunk in stream:
                for call in (chunk.delta.tool_calls if chunk.delta else None) or []:
                    if call.name == "record_answer" and arguments is None:
                        arguments = call.arguments
        if arguments is None:
            raise ValueError("no record_answer call in the reply")
        return reading_from(json.loads(arguments or "{}"))


def describe_turn(survey: Survey, said: str, last_line: str) -> str:
    """The turn as the LLM gets it: the question, the answers so far, and the caller's words."""
    current = survey.asked or FIELDS[0]
    known = [
        f"{_FIELD_KEY.get(name, name)}: {value}"
        for name, value in survey.sheet_values().items()
        if value and name in FIELDS
    ]
    lines = [
        f'Question just asked: {_FIELD_KEY.get(current, current)} ("{QUESTIONS[current].ask}")',
        f'The agent\'s last words: "{last_line}"' if last_line else "",
        f"Answers so far: {'; '.join(known) if known else 'none'}",
        f'What the person said: "{" ".join(said.split())}"',
    ]
    return "\n".join(line for line in lines if line)


def reading_from(arguments: dict[str, Any]) -> Reading:
    """The LLM's record_answer arguments, checked: anything that isn't a real answer is dropped."""
    intent = arguments.get("intent")
    intent = intent if intent in INTENTS else "unclear"
    values: dict[str, object] = {}
    for name in TEXT_FIELDS:
        if (text := clean_text(arguments.get(name))) is not None:
            values[name] = text
    water = arguments.get("water_supply")
    if isinstance(water, bool):
        values["water_supply"] = water
    elif isinstance(water, str) and water.lower() in ("yes", "no"):
        values["water_supply"] = water.lower() == "yes"
    if (days := clean_days(arguments.get("frequency_days"))) is not None:
        values["frequency_days"] = days
    elif (note := clean_note(arguments.get("frequency_note"))) is not None:
        values["frequency_note"] = note
    if (minutes := clean_minutes(arguments.get("duration_minutes"))) is not None:
        values["duration_minutes"] = minutes
    elif (note := clean_note(arguments.get("duration_note"))) is not None:
        values["duration_note"] = note
    if intent == "answer" and not values:
        intent = "unclear"  # "answered", but nothing usable came with it
    asked_about = arguments.get("asked_about")
    if intent == "question":
        asked_about = asked_about if asked_about in ("who", "why", "other") else "other"
    else:
        asked_about = None
    return Reading(intent, values, asked_about, source="llm")  # type: ignore[arg-type]


def asked_just_now(current: str, last_line: str) -> bool:
    """Whether the agent's last line was the current question, rather than "can you hear me?" or
    "no problem, take your time": a bare "હા" answers whichever it was."""
    question = QUESTIONS[current]
    return not last_line or question.ask in last_line or question.again in last_line


def quick_reading(current: str, said: str) -> Reading | None:
    """A reading without the LLM, only when every word of a short answer is understood."""
    if current == "water_supply" and (comes := yes_or_no(said, strict=True)) is not None:
        return Reading("answer", {"water_supply": comes}, source="rules")
    if current == "frequency" and (days := days_from(said, strict=True)) is not None:
        return Reading("answer", {"frequency_days": days}, source="rules")
    if current == "duration" and (minutes := minutes_from(said, strict=True)) is not None:
        return Reading("answer", {"duration_minutes": minutes}, source="rules")
    return None


# Longer than this, a name or place the rules cut out of a sentence is more likely the sentence.
FALLBACK_MAX_WORDS = 3


def fallback_reading(current: str, said: str, *, asked: bool = True) -> Reading:
    """The best the rules can do with any answer, for when the LLM isn't there."""
    if not said.strip():
        return Reading("unclear", source="fallback")
    if says_goodbye(said):
        return Reading("goodbye", source="fallback")
    if is_busy(said):
        return Reading("busy", source="fallback")
    if asks_to_repeat(said):
        return Reading("repeat", source="fallback")
    value: object | None
    if current in TEXT_FIELDS:
        value = clean_text(said)
        if value is not None and len(str(value).split()) > FALLBACK_MAX_WORDS:
            value = None
        key = current
    elif current == "water_supply":
        value, key = yes_or_no(said), "water_supply"
        if value is not None and not asked:  # "હા" to "can you hear me?"
            return Reading("acknowledge", source="fallback")
    elif current == "frequency":
        value, key = days_from(said), "frequency_days"
    else:
        value, key = minutes_from(said), "duration_minutes"
    if value is None:
        return Reading("unclear", source="fallback")
    return Reading("answer", {key: value}, source="fallback")
