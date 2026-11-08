"""Where the call is in the survey, what's been answered, and what to say next.

One caller turn goes in (a Reading, from reader.py) and one line comes out (a Reply). The flow, not
the LLM, decides what that line is, so every reply is one of the script's lines (script.py):
- an answer moves on to the next question, saying back what was heard so a mistake is caught;
- an answer to a later question, or a correction to an earlier one, is taken wherever it's given;
- "શું?" repeats the question, "who is this?" gets an answer and then the question again;
- an unclear answer is asked again in other words, and after three tries the survey moves on, so a
  call can never go round in circles;
- "no water" skips how often and how long, and "busy" or "not interested" ends the call politely.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from agent.survey.answers import (
    NOT_APPLICABLE,
    UNCLEAR,
    Answers,
    duration_text,
    frequency_text,
    water_text,
)
from agent.survey.script import (
    BUSY,
    CHECK_IN,
    DECLINED,
    DONT_KNOW,
    EARLY_GOODBYE,
    FIELDS,
    MOVE_ON,
    NO_WATER,
    ONCE_MORE,
    QUESTIONS,
    RECORDED,
    THANKS,
    TO_WATER,
    WAITING,
    WATER_DETAILS,
    Script,
)

Intent = Literal[
    "answer", "unclear", "repeat", "question", "acknowledge", "wait", "busy", "refuse", "goodbye"
]  # fmt: skip
INTENTS: tuple[str, ...] = (
    "answer", "unclear", "repeat", "question", "acknowledge", "wait", "busy", "refuse", "goodbye",
)  # fmt: skip
AskedAbout = Literal["who", "why", "other"]
Status = Literal["completed", "partial", "busy", "declined", "no_answer"]

# Answers fields a Reading may carry, as cleaned values (reader.py does the cleaning).
TEXT_FIELDS = ("name", "village", "taluka", "district")
VALUE_KEYS = (
    *TEXT_FIELDS, "water_supply", "frequency_days", "frequency_note", "duration_minutes", "duration_note",
)  # fmt: skip

NOTE_LABELS = {
    "name": "name", "village": "village", "taluka": "taluka", "district": "district",
    "water_supply": "water supply", "frequency": "how often", "duration": "time per day",
}  # fmt: skip

MAX_RETRIES = 2  # an unclear answer gets the question again twice; the third time the survey moves on
MAX_TURNS = 5  # turns on one question, whatever was said, before moving on


@dataclass(frozen=True)
class Reading:
    """What one caller turn said, as reader.py understood it."""

    intent: Intent
    values: dict[str, object] = field(default_factory=dict)  # keys from VALUE_KEYS
    asked_about: AskedAbout | None = None  # for intent "question"
    source: Literal["llm", "rules", "fallback"] = "llm"


@dataclass(frozen=True)
class Reply:
    line: str
    end: bool = False  # hang up once it has been said
    changed: tuple[str, ...] = ()  # survey fields whose answer changed this turn


class Survey:
    def __init__(self, script: Script | None = None) -> None:
        self.script = script or Script()
        self.answers = Answers()
        self.asked: str | None = None  # the field whose question was asked last
        self.skipped: set[str] = set()  # asked MAX_RETRIES + 1 times without a usable answer
        self.status: Status | None = None  # set once the call is over
        self.stopped_at: str | None = None  # the question still open when the call ended early
        self.spoke = False  # the person said anything the survey heard
        self.waiting = False  # they asked us to hold on: silence is expected for a while
        self._retries: Counter[str] = Counter()  # unclear answers, per question
        self._reasks: Counter[str] = Counter()  # times a question was asked again, for any reason
        self._turns: Counter[str] = Counter()
        self._told_about_water = False

    @property
    def finished(self) -> bool:
        return self.status is not None

    @property
    def question(self) -> str:
        """The current question, as first asked."""
        return QUESTIONS[self.asked or FIELDS[0]].ask

    def opening(self) -> tuple[str, str]:
        """The introduction and the first question. They're said one after the other: the
        introduction can't be cut off, the question can, by someone answering straight away."""
        self.asked = FIELDS[0]
        return self.script.intro(), QUESTIONS[self.asked].ask

    def respond(self, reading: Reading) -> Reply:
        if self.finished:
            return Reply("", end=True)
        self.spoke = True
        self.waiting = reading.intent == "wait"
        changed = self._apply(reading.values)
        if reading.intent == "busy":
            return self._finish("busy", BUSY, changed)
        if reading.intent == "refuse":
            return self._finish("declined", DECLINED, changed)
        if reading.intent == "goodbye":
            return self._finish(self._status_when_cut_short(), EARLY_GOODBYE, changed)

        current = self.asked or FIELDS[0]
        upcoming = self._next()
        # "Who is this? I'm Ramesh": the question gets its answer whatever else the turn did.
        reply_to = self._answer(reading.asked_about) if reading.intent == "question" else ""
        if upcoming != current:  # the current question is answered (or no longer applies)
            lead = " ".join(p for p in (reply_to, self._ack(changed)) if p)
            return self._move_on(upcoming, lead=lead, changed=changed)
        if changed:  # a correction or an answer ahead of time; the current question still stands
            heard = f"બરાબર, {_join_and([self._phrase(f) for f in changed])}."
            return Reply(" ".join(p for p in (reply_to, heard, self.question) if p), changed=changed)
        if reading.intent == "wait":
            return Reply(WAITING)

        self._turns[current] += 1
        if self._turns[current] >= MAX_TURNS:
            return self._give_up_on(current)
        if reading.intent in ("repeat", "acknowledge"):
            return Reply(self.question)
        if reading.intent == "question":
            return Reply(f"{reply_to} {self.question}")
        self._retries[current] += 1
        if self._retries[current] > MAX_RETRIES:
            return self._give_up_on(current)
        return Reply(self._ask_again(current))

    def didnt_hear(self) -> str:
        """Speech came through with no words in it: ask again, without counting it against them."""
        current = self.asked or FIELDS[0]
        self._turns[current] += 1
        return self._ask_again(current)

    def check_in(self) -> str:
        return CHECK_IN

    def end(self) -> Status:
        """The call ended without a goodbye from the flow: a hang-up, silence or the time limit."""
        if self.status is None:
            self.status = self._status_when_cut_short()
            self.stopped_at = None if self.status == "completed" else self.asked
            self.asked = None
        return self.status

    def note(self) -> str:
        """For the sheet's Notes column: how the call went, when that isn't obvious from the answers."""
        unclear = [NOTE_LABELS[f] for f in FIELDS if f in self.skipped]
        if self.status == "completed":
            return f"Unclear: {', '.join(unclear)}" if unclear else ""
        if self.status == "partial":
            where = NOTE_LABELS.get(self.stopped_at or "", "")
            return f"Call ended at the {where} question" if where else "Call ended early"
        return {
            "busy": "Busy: asked to be called later",
            "declined": "Didn't want to take part",
            "no_answer": "Picked up, but didn't answer",
        }.get(self.status or "", "")

    # What has been answered -------------------------------------------------------------------

    def is_done(self, field_name: str) -> bool:
        a = self.answers
        if field_name in self.skipped:
            return True
        if field_name in WATER_DETAILS and (a.water_supply is False or "water_supply" in self.skipped):
            return True
        if field_name == "frequency":
            return a.frequency_days is not None or a.frequency_note is not None
        if field_name == "duration":
            return a.duration_minutes is not None or a.duration_note is not None
        if field_name == "water_supply":
            return a.water_supply is not None
        return getattr(a, field_name) is not None

    def sheet_values(self) -> dict[str, str]:
        """Every answer the way the sheet shows it; blank for a question not reached yet."""
        a = self.answers
        values: dict[str, str] = {}
        for name in TEXT_FIELDS:
            values[name] = getattr(a, name) or (UNCLEAR if name in self.skipped else "")
        if a.water_supply is not None:
            values["water_supply"] = water_text(a.water_supply)
        else:
            values["water_supply"] = UNCLEAR if "water_supply" in self.skipped else ""
        texts = {
            "frequency": frequency_text(a.frequency_days, a.frequency_note, written=True),
            "duration": duration_text(a.duration_minutes, a.duration_note, written=True),
        }
        for name in WATER_DETAILS:
            if a.water_supply is False:
                values[name] = NOT_APPLICABLE
            elif text := texts[name]:
                values[name] = text
            elif name in self.skipped or "water_supply" in self.skipped:
                values[name] = UNCLEAR
            else:
                values[name] = ""
        return values

    # Internals ----------------------------------------------------------------------------------

    def _next(self) -> str | None:
        return next((f for f in FIELDS if not self.is_done(f)), None)

    def _apply(self, values: dict[str, object]) -> tuple[str, ...]:
        """Take every answer in the turn, wherever it belongs. Returns the fields that changed."""
        a = self.answers
        changed: set[str] = set()
        for name in TEXT_FIELDS:
            value = values.get(name)
            if isinstance(value, str) and value and value != getattr(a, name):
                setattr(a, name, value)
                changed.add(name)
        days, days_note = values.get("frequency_days"), values.get("frequency_note")
        minutes, minutes_note = values.get("duration_minutes"), values.get("duration_note")
        water = values.get("water_supply")
        details = any(v is not None for v in (days, days_note, minutes, minutes_note))
        if details and water is None and a.water_supply is not True:
            water = True  # "એકાંતરે આવે છે" says that water comes, too
        if isinstance(water, bool) and water != a.water_supply:
            a.water_supply = water
            changed.add("water_supply")
            if not water:
                a.frequency_days = a.frequency_note = a.duration_minutes = a.duration_note = None
        if a.water_supply is not False:
            if isinstance(days, float) and days != a.frequency_days:
                a.frequency_days, a.frequency_note = days, None
                changed.add("frequency")
            elif isinstance(days_note, str) and a.frequency_days is None and days_note != a.frequency_note:
                a.frequency_note = days_note
                changed.add("frequency")
            if isinstance(minutes, int) and minutes != a.duration_minutes:
                a.duration_minutes, a.duration_note = minutes, None
                changed.add("duration")
            elif (
                isinstance(minutes_note, str)
                and a.duration_minutes is None
                and minutes_note != a.duration_note
            ):
                a.duration_note = minutes_note
                changed.add("duration")
        for name in changed:
            self.skipped.discard(name)
        return tuple(f for f in FIELDS if f in changed)

    def _move_on(self, upcoming: str | None, *, lead: str, changed: tuple[str, ...] = ()) -> Reply:
        if upcoming is None:
            if "water_supply" in changed and self.answers.water_supply is False:
                lead = NO_WATER
            return self._finish("completed", " ".join(p for p in (lead, RECORDED, THANKS) if p), changed)
        self.asked = upcoming
        parts = [lead]
        if upcoming == "water_supply" and not self._told_about_water:
            parts.append(TO_WATER)
            self._told_about_water = True
        parts.append(QUESTIONS[upcoming].ask)
        return Reply(" ".join(p for p in parts if p), changed=changed)

    def _ask_again(self, current: str) -> str:
        """The question in other words; the next time, introduced as asking once more."""
        self._reasks[current] += 1
        question = QUESTIONS[current]
        return question.again if self._reasks[current] % 2 else f"{ONCE_MORE} {question.ask}"

    def _give_up_on(self, current: str) -> Reply:
        self.skipped.add(current)
        return self._move_on(self._next(), lead=MOVE_ON)

    def _finish(self, status: Status, line: str, changed: tuple[str, ...] = ()) -> Reply:
        self.status = status
        self.stopped_at = None if status == "completed" else self.asked
        self.asked = None
        return Reply(line, end=True, changed=changed)

    def _status_when_cut_short(self) -> Status:
        if self._next() is None:
            return "completed"
        answered = any(v is not None for v in self.answers.as_dict().values())
        return "partial" if answered or self.spoke else "no_answer"

    def _answer(self, asked_about: AskedAbout | None) -> str:
        if asked_about == "who":
            return self.script.who()
        if asked_about == "why":
            return self.script.why()
        return DONT_KNOW

    def _ack(self, changed: tuple[str, ...]) -> str:
        """Say back what was just answered, so a misheard name or place gets corrected now."""
        shown = [f for f in changed if self._phrase(f)]
        if not shown:
            return ""
        if len(shown) > 1:
            return f"બરાબર, {_join_and([self._phrase(f) for f in shown])}."
        a, only = self.answers, shown[0]
        if only == "name":
            return f"આભાર, {a.name}."
        if only == "village":
            return f"સરસ, {a.village}."
        if only == "taluka":
            return f"{a.taluka} તાલુકો, બરાબર."
        if only == "district":
            return f"{a.district} જિલ્લો."
        if only == "water_supply":
            return "સારું." if a.water_supply else NO_WATER
        if only == "frequency":
            return f"{frequency_text(a.frequency_days, a.frequency_note)}, ઠીક છે."
        return f"{duration_text(a.duration_minutes, a.duration_note)}, બરાબર."

    def _phrase(self, field_name: str) -> str:
        a = self.answers
        if field_name == "name":
            return a.name or ""
        if field_name == "village":
            return f"{a.village} ગામ" if a.village else ""
        if field_name == "taluka":
            return f"{a.taluka} તાલુકો" if a.taluka else ""
        if field_name == "district":
            return f"{a.district} જિલ્લો" if a.district else ""
        if field_name == "water_supply":
            return "" if a.water_supply is None else "પાણી આવે છે" if a.water_supply else "પાણી નથી આવતું"
        if field_name == "frequency":
            return frequency_text(a.frequency_days, a.frequency_note) or ""
        return duration_text(a.duration_minutes, a.duration_note) or ""


def _join_and(items: list[str]) -> str:
    """a; a અને b; a, b અને c."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} અને {items[-1]}"
