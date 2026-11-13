"""Where the call is in the survey, what's been answered, and what to say next.

One caller turn goes in (a Reading, from reader.py) and one line comes out (a Reply). The flow, not
the LLM, decides what that line is, so every reply is one of the script's lines (script.py):
- an answer moves on to the next question, saying back what was heard so a mistake is caught;
- a village, taluka or district is looked up in the list of Gujarat's places (places/), read back
  ("ખાંભા તાલુકો, બરાબર?") and written down only once the person says yes. A name that isn't in the
  list is asked for again, and never written down;
- an answer to a later question, or a correction to an earlier one, is taken wherever it's given;
- "શું?" repeats the question, "who is this?" gets an answer and then the question again;
- an unclear answer is asked again in other words, and after three tries the survey moves on, so a
  call can never go round in circles;
- "no water" skips how often and how long, and "busy" or "not interested" ends the call politely.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal

from agent.places.keys import keys
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
    CONFIRM_PLACE,
    CONFIRM_SEVERAL,
    CONFIRMED,
    DECLINED,
    DONT_KNOW,
    EARLY_GOODBYE,
    FIELDS,
    MOVE_ON,
    NO_WATER,
    ONCE_MORE,
    PLACE_FIELDS,
    PLACE_PHRASES,
    QUESTIONS,
    RECORDED,
    THANKS,
    TO_WATER,
    WAITING,
    WATER_DETAILS,
    Script,
)

if TYPE_CHECKING:
    from agent.places.gazetteer import Gazetteer, Match

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
# A place in English letters, as the LLM spells it: one more way to find it in the list.
SPELLING_KEYS = {"village": "village_en", "taluka": "taluka_en", "district": "district_en"}
VALUE_KEYS = (
    *TEXT_FIELDS, *SPELLING_KEYS.values(), "water_supply", "frequency_days", "frequency_note",
    "duration_minutes", "duration_note",
)  # fmt: skip

NOTE_LABELS = {
    "name": "name", "village": "village", "taluka": "taluka", "district": "district",
    "water_supply": "water supply", "frequency": "how often", "duration": "time per day",
}  # fmt: skip

# An unclear answer, a place that isn't in the list, or a "no" to a place read back gets the question
# again twice; the third time the survey moves on.
MAX_RETRIES = 2
MAX_TURNS = 5  # turns on one question, whatever was said, before moving on


@dataclass(frozen=True)
class Reading:
    """What one caller turn said, as reader.py understood it."""

    intent: Intent
    values: dict[str, object] = field(default_factory=dict)  # keys from VALUE_KEYS
    asked_about: AskedAbout | None = None  # for intent "question"
    source: Literal["llm", "rules", "fallback"] = "llm"
    confirm: bool | None = None  # to a place read back ("ખાંભા તાલુકો, બરાબર?"): yes, no, or neither


@dataclass(frozen=True)
class Reply:
    line: str
    end: bool = False  # hang up once it has been said
    changed: tuple[str, ...] = ()  # survey fields whose answer changed this turn


@dataclass(frozen=True)
class HeardPlace:
    """A place the person named, found in the list, and read back for their yes."""

    field: str  # "village", "taluka" or "district"
    sheet: str  # what the sheet gets once they say yes: "ખાંભા (Khambha)"
    spoken: str  # what's read back: their words, or the list's name in Gujarati
    match: Match | None = None  # where it is in the list; None when there's no list to check against
    city: bool = False  # a town or city, to the village question: "તમારું શહેર ..."

    def sounds_like(self, said: Sequence[str]) -> bool:
        """Whether they've said this place again, by any name it was found by."""
        names = [self.spoken]
        if self.match is not None:
            names += [self.match.heard, self.match.place.name, self.match.place.gujarati or ""]
        ours = set().union(*(keys(n) for n in names if n))
        return any(keys(s) & ours for s in said)


@dataclass
class _PlaceTurn:
    """What a turn did to the places: confirmed, turned down, not found in the list, or newly heard."""

    confirmed: list[str] = field(default_factory=list)  # read back and agreed to: in the answers now
    refined: list[str] = field(default_factory=list)  # confirmed before, now pinned to the right place
    rejected: str | None = None  # read back and turned down: asked for again
    unlisted: list[str] = field(default_factory=list)  # named, but nothing in the list sounds like it
    heard: list[str] = field(default_factory=list)  # named and found: read back next

    @property
    def progress(self) -> bool:
        return bool(self.confirmed or self.rejected or self.unlisted or self.heard)


class Survey:
    def __init__(self, script: Script | None = None, *, places: Gazetteer | None = None) -> None:
        self.script = script or Script()
        # Gujarat's places, to check a village, taluka or district against; None takes any name, as
        # heard (and still reads it back for a yes).
        self.places = places
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
        self._pending: dict[str, HeardPlace] = {}  # heard and found, waiting for a yes
        self._confirmed: dict[str, HeardPlace] = {}  # agreed to: these are in the answers
        self._unlisted: dict[str, str] = {}  # the last name heard for a place that isn't in the list
        self._told_unlisted: set[str] = set()
        self._confirming = False  # the last line read places back and asked "બરાબર?"
        self.confirmation = ""  # that line's question

    @property
    def confirming(self) -> bool:
        """The last line read places back, and they're still waiting for a yes or no."""
        return self._confirming and bool(self._pending)

    @property
    def pending(self) -> dict[str, str]:
        """Places heard but not confirmed yet, and the name each is read back as."""
        return {f: self._pending[f].spoken for f in PLACE_FIELDS if f in self._pending}

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
        confirming, self._confirming = self.confirming, False
        changed = set(self._apply(reading.values))
        places = self._hear_places(reading, confirming)
        changed.update(places.confirmed, places.refined)
        for name in changed:
            self.skipped.discard(name)
        done = tuple(f for f in FIELDS if f in changed)
        if reading.intent == "busy":
            return self._finish("busy", BUSY, done)
        if reading.intent == "refuse":
            return self._finish("declined", DECLINED, done)
        if reading.intent == "goodbye":
            return self._finish(self._status_when_cut_short(), EARLY_GOODBYE, done)

        current = self.asked or FIELDS[0]
        # "Who is this? I'm Ramesh": the question gets its answer whatever else the turn did.
        reply_to = self._answer(reading.asked_about) if reading.intent == "question" else ""
        lead = _join(reply_to, self._ack(done, places.confirmed))
        if places.rejected:  # "ના" to a place read back
            return self._ask_for_place(places.rejected, lead, done)
        if current in places.unlisted and current not in self._pending:
            return self._ask_for_place(current, lead, done, unlisted=True)
        if self._pending:  # places heard: read back for a yes before they go in the sheet
            if not (places.progress or done):  # "શું?", unclear words, or a "હા" to something else
                if reading.intent == "wait":
                    return Reply(WAITING)
                if self._no_headway(current, reading.intent):
                    return self._give_up_on(current)
            return self._read_back(lead, done)

        upcoming = self._next()
        if upcoming != current:  # the current question is answered (or no longer applies)
            return self._move_on(upcoming, lead=lead, changed=done)
        if done:  # a correction or an answer ahead of time; the current question still stands
            said_back = [self._phrase(f) for f in done if f not in PLACE_FIELDS]
            heard = f"બરાબર, {_join_and(said_back)}." if said_back else self._ack(done, places.confirmed)
            return Reply(_join(reply_to, heard, self.question), changed=done)
        if reading.intent == "wait":
            return Reply(WAITING)
        if self._no_headway(current, reading.intent):
            return self._give_up_on(current)
        if reading.intent in ("repeat", "acknowledge"):
            return Reply(self.question)
        if reading.intent == "question":
            return Reply(f"{reply_to} {self.question}")
        return Reply(self._ask_again(current))

    def didnt_hear(self) -> str:
        """Speech came through with no words in it: ask again, without counting it against them."""
        current = self.asked or FIELDS[0]
        self._turns[current] += 1
        if self.confirming:
            return self.confirmation
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
        about_places = self._place_notes()
        unclear = [NOTE_LABELS[f] for f in FIELDS if f in self.skipped and f not in about_places]
        if self.status == "completed":
            how = f"Unclear: {', '.join(unclear)}" if unclear else ""
        elif self.status == "partial":
            where = NOTE_LABELS.get(self.stopped_at or "", "")
            how = f"Call ended at the {where} question" if where else "Call ended early"
        else:
            how = {
                "busy": "Busy: asked to be called later",
                "declined": "Didn't want to take part",
                "no_answer": "Picked up, but didn't answer",
            }.get(self.status or "", "")
        return "; ".join(n for n in (how, *about_places.values(), *self._mismatches()) if n)

    def _place_notes(self) -> dict[str, str]:
        """A place that never made it into the sheet, and why: not in the list, or not confirmed."""
        notes: dict[str, str] = {}
        for f in PLACE_FIELDS:
            label = NOTE_LABELS[f].capitalize()
            if f in self._pending:
                notes[f] = f"{label} not confirmed (heard: {self._pending[f].sheet})"
            elif f in self._unlisted and getattr(self.answers, f) is None:
                notes[f] = f"{label} not in the list (heard: {self._unlisted[f]})"
        return notes

    def _mismatches(self) -> list[str]:
        """Confirmed places that don't go together in the list: worth a look, though the person
        confirmed each one (a village can be named after its old taluka)."""
        if self.places is None:
            return []
        found = {f: p.match for f, p in self._confirmed.items() if p.match is not None}
        village, taluka, district = (found.get(f) for f in PLACE_FIELDS)
        notes = []
        if village and taluka and not self.places.village_in_taluka(village, taluka):
            notes.append(f"Check: no {village.place.name} in {taluka.place.name} taluka in the list")
        if taluka and district and not self.places.taluka_in_district(taluka, district):
            where = taluka.place.district
            said = district.place.name
            notes.append(f"Check: {taluka.place.name} taluka is in {where} district, not {said}")
        return notes

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
        """Take every answer in the turn, wherever it belongs, except places (see _hear_places).
        Returns the fields that changed."""
        a = self.answers
        changed: set[str] = set()
        for name in TEXT_FIELDS:
            if name in PLACE_FIELDS:
                continue  # a place goes in only once it's confirmed: see _hear_places
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

    def _no_headway(self, current: str, intent: str) -> bool:
        """Count a turn that got nowhere. True once the question has had enough of them."""
        self._turns[current] += 1
        if intent not in ("repeat", "acknowledge", "question"):
            self._retries[current] += 1
        return self._turns[current] >= MAX_TURNS or self._retries[current] > MAX_RETRIES

    def _give_up_on(self, current: str, *, lead: str = "", changed: tuple[str, ...] = ()) -> Reply:
        self.skipped.add(current)
        self._pending.clear()
        return self._move_on(self._next(), lead=_join(lead, MOVE_ON), changed=changed)

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

    def _ack(self, changed: tuple[str, ...], confirmed: Sequence[str] = ()) -> str:
        """Say back what was just answered, so a misheard name gets corrected now. A place has been
        read back and agreed to already: it gets a plain "સરસ." instead."""
        shown = [f for f in changed if f not in PLACE_FIELDS and self._phrase(f)]
        if not shown:
            return CONFIRMED[confirmed[-1]] if confirmed else ""
        if len(shown) > 1:
            return f"બરાબર, {_join_and([self._phrase(f) for f in shown])}."
        a, only = self.answers, shown[0]
        if only == "name":
            return f"આભાર, {a.name}."
        if only == "water_supply":
            return "સારું." if a.water_supply else NO_WATER
        if only == "frequency":
            return f"{frequency_text(a.frequency_days, a.frequency_note)}, ઠીક છે."
        return f"{duration_text(a.duration_minutes, a.duration_note)}, બરાબર."

    # Places: found in the list, read back, confirmed ----------------------------------------------

    def _hear_places(self, reading: Reading, confirming: bool) -> _PlaceTurn:
        """The places in a turn: a yes or no to those read back, and new ones, checked in the list."""
        turn = _PlaceTurn()
        said = {f: _wordings(reading.values, f) for f in PLACE_FIELDS}
        if confirming:
            for f in [f for f in PLACE_FIELDS if f in self._pending]:
                heard = self._pending[f]
                if said[f] and heard.sounds_like(said[f]):  # "ખાંભા" again, or "હા, ખાંભા"
                    said[f] = []
                    yes = reading.confirm is not False
                elif said[f]:  # another name: a correction, checked and read back below
                    del self._pending[f]
                    continue
                else:
                    yes = reading.confirm is True
                if yes:
                    self._commit(heard)
                    turn.confirmed.append(f)
            if reading.confirm is False and self._pending and not any(said.values()):
                turn.rejected = next(f for f in PLACE_FIELDS if f in self._pending)
                self._pending.clear()
        for f in PLACE_FIELDS:
            if not said[f] or (f in self._confirmed and self._confirmed[f].sounds_like(said[f])):
                continue  # nothing said, or the answer already given
            if (heard := self._look_up(f, said[f])) is None:
                self._unlisted[f] = said[f][0]
                self._pending.pop(f, None)
                turn.unlisted.append(f)
            else:
                self._pending[f] = heard
                turn.heard.append(f)
        if turn.confirmed:
            turn.refined = [f for f in self._refine() if f not in turn.confirmed]
        return turn

    def _look_up(self, f: str, said: list[str]) -> HeardPlace | None:
        if self.places is None:
            return HeardPlace(f, said[0], said[0])
        found = self.places.match(f, said, **self._context(f, confirmed_only=False))
        if found is None:
            return None
        return HeardPlace(f, found.sheet, found.spoken, found, city=f == "village" and found.is_city)

    def _context(self, f: str, *, confirmed_only: bool) -> dict[str, Match | None]:
        """The other places, as found: what narrows down which place of a name is meant."""
        context: dict[str, Match | None] = {}
        for other in PLACE_FIELDS:
            if other == f:
                continue
            heard = (
                self._confirmed.get(other)
                if confirmed_only
                else self._pending.get(other, self._confirmed.get(other))
            )
            context[other] = heard.match if heard else None
        return context

    def _commit(self, heard: HeardPlace) -> None:
        setattr(self.answers, heard.field, heard.sheet)
        self._confirmed[heard.field] = heard
        self._pending.pop(heard.field, None)
        self._unlisted.pop(heard.field, None)

    def _refine(self) -> list[str]:
        """Which place of a confirmed name is meant, now that more is confirmed: the Navagam in their
        taluka, the Kalol in their district. Returns the fields whose sheet value changed."""
        if self.places is None:
            return []
        changed = []
        for f, heard in list(self._confirmed.items()):
            if heard.match is None or len(heard.match.places) < 2:
                continue
            better = self.places.rank(heard.match, **self._context(f, confirmed_only=True))
            if better.place == heard.match.place:
                continue
            self._confirmed[f] = replace(heard, match=better, sheet=better.sheet)
            if better.sheet != getattr(self.answers, f):
                setattr(self.answers, f, better.sheet)
                changed.append(f)
        return changed

    def _read_back(self, lead: str, changed: tuple[str, ...]) -> Reply:
        """The places heard, read back for a yes: "તમારું ગામ ખાંભા, બરાબર?"."""
        heard = [self._pending[f] for f in PLACE_FIELDS if f in self._pending]
        if len(heard) == 1:
            question = CONFIRM_PLACE["city" if heard[0].city else heard[0].field].format(heard[0].spoken)
        else:
            phrases = [PLACE_PHRASES["city" if h.city else h.field].format(h.spoken) for h in heard]
            question = CONFIRM_SEVERAL.format(_join_and(phrases))
        self._confirming = True
        self.confirmation = question
        return Reply(_join(lead, question), changed=changed)

    def _ask_for_place(self, f: str, lead: str, changed: tuple[str, ...], *, unlisted: bool = False) -> Reply:
        """A place read back was wrong, or isn't in the list: ask for it again, or in the end move on."""
        self._retries[f] += 1
        if self._retries[f] > MAX_RETRIES:
            return self._give_up_on(f, lead=lead, changed=changed)
        self.asked = f
        if unlisted and f not in self._told_unlisted:
            self._told_unlisted.add(f)
            return Reply(_join(lead, QUESTIONS[f].unlisted), changed=changed)
        return Reply(_join(lead, self._ask_again(f)), changed=changed)

    def _phrase(self, field_name: str) -> str:
        a = self.answers
        if field_name == "name":
            return a.name or ""
        if field_name == "water_supply":
            return "" if a.water_supply is None else "પાણી આવે છે" if a.water_supply else "પાણી નથી આવતું"
        if field_name == "frequency":
            return frequency_text(a.frequency_days, a.frequency_note) or ""
        return duration_text(a.duration_minutes, a.duration_note) or ""


def _join(*parts: str) -> str:
    return " ".join(p for p in parts if p)


def _wordings(values: dict[str, object], f: str) -> list[str]:
    """The ways a place came through in a reading: their words in Gujarati, the LLM's spelling."""
    found = [values.get(f), values.get(SPELLING_KEYS[f])]
    return [w for w in found if isinstance(w, str) and w.strip()]


def _join_and(items: list[str]) -> str:
    """a; a અને b; a, b અને c."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} અને {items[-1]}"
