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
import dataclasses
import json
import logging
import re
from typing import Any

from livekit.agents import llm

from agent.survey.answers import (
    age_from,
    asks_to_repeat,
    clean_age,
    clean_days,
    clean_minutes,
    clean_note,
    clean_text,
    days_from,
    is_busy,
    minutes_from,
    says_goodbye,
    says_its_wrong,
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
- age: how old they are, in whole years (ઉંમર). "પચાસ" = 50, "લગભગ 45" = 45, a range ("40-45") = the middle, rounded down: 42.
- village: their village or town (ગામ).
- taluka: their taluka (તાલુકો).
- district: their district (જિલ્લો).
- water_supply: does water come to them? yes or no.
- frequency_days: every how many days water comes. 1 = every day (રોજ), 2 = alternate days (એકાંતરે), 3 = every third day, 7 = once a week, 3.5 = twice a week.
- duration_minutes: on a day it comes, how long water runs, in minutes. અડધો કલાક = 30, પોણો કલાક = 45, એક કલાક = 60, દોઢ કલાક = 90, અઢી કલાક = 150. A time range: "સવારે 6 થી 8" = 120.

The words come from speech recognition: expect Gujarati, Hindi or English words in either script, Kathiawadi, Surti or other local speech, and recognition mistakes.

Rules:
- Record only what the person actually said. Never guess, and never fill a field from general knowledge (don't add a district because you know where a village is).
- They usually answer the question just asked, but may answer several at once ("રમેશ પટેલ, પચાસ વર્ષ" is a name and an age), or correct an earlier answer: record those too.
- A correction says the earlier answer was wrong ("ના, ગામ ખાંભા નહીં, ખંભાળિયા"), or gives a different answer right after the agent's last words said that answer back. It's intent answer, even when it doesn't answer the question just asked.
- wrong_answer is only for a turn that brings nothing new: an answer already given, said again unchanged, instead of answering the question just asked (their name again when asked their age), or words that answer none of the questions ("હું ખેતી કરું છું" when asked the village). A new or changed answer to any question, asked or not, is intent answer. Never call an answer wrong because it seems untrue or unlikely.
- A taluka or district is often named after its main village: the village's name given to the taluka or district question ("ખાંભા", "ખાંભા જ") answers it. That isn't wrong_answer.
- Write names and places in Gujarati script, every word of them ("રમેશભાઈ પટેલ", never "રમેશભાઈ Patel"), spelled as commonly written ("ભાવનગર", "રાજકોટ"), without filler such as "મારું નામ", "ગામ" or "છે". Keep ભાઈ or બેન if they said it.
- When how often or how long isn't a plain number ("ક્યારેક", "નક્કી નહીં"), put their words in frequency_note or duration_note.
- "એક મિનિટ" or "બે મિનિટ" on its own usually means "hold on" (intent wait), not a duration.
- When the agent's last words weren't the question (for example "હેલો, તમને મારો અવાજ સંભળાય છે?"), a bare "હા" answers those words: intent acknowledge, not an answer to the question.

intent:
- answer: they answered at least one question, or corrected an earlier answer.
- wrong_answer: the words are clear but bring nothing new: an answer already given, said again, or words that answer no question (see the rules).
- unclear: you can't make out what they said, or it's too vague to record.
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
- name: "રમેશ પટેલ, ઉંમર પચાસ" -> answer, name "રમેશ પટેલ", age 50
- age: "મારી ઉંમર પિસ્તાલીસ વર્ષ" -> answer, age 45
- age, answers so far name રમેશ પટેલ: "રમેશ પટેલ" -> intent wrong_answer
- age, the agent's last words "આભાર, મહેશ. તમારી ઉંમર કેટલી છે?": "મહેશ નહીં, રમેશ" -> answer, name "રમેશ"
- village: "હું ખેતી કરું છું" -> intent wrong_answer
- taluka, answers so far village ખાંભા: "ખાંભા જ" -> answer, taluka "ખાંભા"
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
            "age": {"type": "number", "description": "Their age in years."},
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
                reading = await asyncio.wait_for(self._ask_llm(survey, said, last_line), self._timeout)
            except Exception as e:  # any failure: the rules below keep the call going
                logger.warning("the LLM couldn't read the answer, using the rules instead: %r", e)
            else:
                return checked_against_words(reading, said)
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
    if (age := clean_age(arguments.get("age"))) is not None:
        values["age"] = age
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


_LATIN = re.compile(r"[A-Za-z]")
_EDGE = " \t\n.,!?।;:\"'`()[]{}<>-–—…"


def checked_against_words(reading: Reading, said: str) -> Reading:
    """Slips the LLM makes that the person's own words catch, tested in evals/test_reading.py."""
    values, intent = dict(reading.values), reading.intent
    # Gujarati number words misread ("બાસઠ", 62, as 52): with one number in the turn, it's the age.
    if "age" in values and (counted := age_from(said)) is not None and counted != values["age"]:
        logger.info("the LLM read the age as %s; the words say %s", values["age"], counted)
        values["age"] = counted
    # "ના, ગામ ખાંભા નહીં, ખંભાળિયા" while asked the taluka: a correction, not a wrong answer, so
    # it may replace the village it corrects.
    if intent == "wrong_answer" and values and says_its_wrong(said):
        intent = "answer"
    if (values, intent) != (reading.values, reading.intent):
        reading = dataclasses.replace(reading, values=values, intent=intent)
    return in_their_script(reading, said)


def in_their_script(reading: Reading, said: str) -> Reading:
    """The LLM now and then writes one word of a Gujarati answer in English letters ("રમેશભાઈ Patel"),
    even when told not to. When the person's words had no English letters, each such word is taken
    from what they said instead: the word that stands next to the same neighbour there."""
    if _LATIN.search(said) or not any(
        isinstance(v, str) and _LATIN.search(v) for k, v in reading.values.items() if k in TEXT_FIELDS
    ):
        return reading
    heard = [w.strip(_EDGE) for w in said.split()]
    values = dict(reading.values)
    for key in TEXT_FIELDS:
        if isinstance(value := values.get(key), str) and _LATIN.search(value):
            values[key] = _swap_latin_words(value.split(), heard)
            logger.info(
                "the LLM wrote %r in English letters; using %r from what was said", value, values[key]
            )
    return dataclasses.replace(reading, values=values)


def _swap_latin_words(words: list[str], heard: list[str]) -> str:
    anchors = [(i, heard.index(w)) for i, w in enumerate(words) if not _LATIN.search(w) and w in heard]
    out = list(words)
    for i, word in enumerate(words):
        if not _LATIN.search(word) or not anchors:
            continue
        mine, theirs = min(anchors, key=lambda anchor: abs(anchor[0] - i))  # the nearest kept word
        at = theirs + (i - mine)
        if 0 <= at < len(heard) and heard[at] and not _LATIN.search(heard[at]) and heard[at] not in out:
            out[i] = heard[at]
    return " ".join(out)


def asked_just_now(current: str, last_line: str) -> bool:
    """Whether the agent's last line was the current question, rather than "can you hear me?" or
    "no problem, take your time": a bare "હા" answers whichever it was."""
    question = QUESTIONS[current]
    return not last_line or question.ask in last_line or question.again in last_line


def quick_reading(current: str, said: str) -> Reading | None:
    """A reading without the LLM, only when every word of a short answer is understood."""
    if current == "age" and (age := age_from(said, strict=True)) is not None:
        return Reading("answer", {"age": age}, source="rules")
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
    elif current == "age":
        value, key = age_from(said), "age"
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
