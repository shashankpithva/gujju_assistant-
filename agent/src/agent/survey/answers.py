"""What the person answered: cleaned up, checked, and written the way the sheet shows it.

The LLM (reader.py) reads most answers, but these rules do two jobs of their own:
- short answers they understand completely ("હા", "રોજ", "એક કલાક") skip the LLM, which saves a
  second on the turn and a request from the free tier's budget;
- when the LLM can't be reached, they read what they can, so the call carries on instead of stalling.

Every rule splits text with understanding.words (see gujarati/__init__.py for why not \\b).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields

from agent.gujarati.numbers import to_ascii_digits, value_of
from agent.gujarati.understanding import words

UNCLEAR = "(સ્પષ્ટ નથી)"  # asked, but no usable answer after every try
NOT_APPLICABLE = "—"  # not asked: water doesn't come, so how often and how long don't apply
MAX_TEXT = 60  # characters of a name or place: anything longer is the STT running on

YES, NO = "હા", "ના"


@dataclass
class Answers:
    name: str | None = None
    age: int | None = None  # in years
    village: str | None = None
    taluka: str | None = None
    district: str | None = None
    water_supply: bool | None = None
    frequency_days: float | None = None  # every how many days water comes: 1 daily, 2 alternate days
    frequency_note: str | None = None  # their words, when it isn't a regular number of days
    duration_minutes: int | None = None  # how long it runs on a day it comes
    duration_note: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


# Cleaning up a name or a place -------------------------------------------------------------------

# Words around an answer that aren't part of it: "મારું નામ રમેશ છે", "ખાંભા ગામ", "અમરેલી જિલ્લો".
_LEADING = {
    "મારું", "મારો", "મારી", "અમારું", "અમારો", "અમારી", "અમારા", "હું", "તો", "જી", "હા", "હાં", "એ",
    "નામ", "ગામ", "ગામનું", "ગામનો", "તાલુકો", "તાલુકા", "તાલુકાનું", "જિલ્લો", "જીલ્લો", "જિલ્લા",
    "જીલ્લા", "જિલ્લાનું", "my", "name", "is", "village", "taluka", "district", "it's", "its", "the",
    "sir", "સાહેબ",
}  # fmt: skip
_TRAILING = {
    "છે", "છું", "છીએ", "તો", "જી", "ગામ", "તાલુકો", "તાલુકા", "જિલ્લો", "જીલ્લો", "જિલ્લા", "જીલ્લા",
    "બોલું", "બોલુ", "is", "village", "taluka", "district", "સાહેબ",
}  # fmt: skip
# Never an answer to "what's your name?" or "which village?", however the STT wrote it.
_NOT_ANSWERS = {
    "શું", "શુ", "કોણ", "કેમ", "હેલો", "હલો", "hello", "hallo", "hi", "બોલો", "બોલ", "હં", "હમ", "હમ્મ",
    "ઓકે", "ok", "okay", "ના", "નહીં", "નહિ", "હા", "હાં", "જી", "what", "who", "yes", "no", "ખબર",
    "નથી", "null", "none", "unknown", "n/a", "na", "-", "—", "?", "unclear", "અજાણ્યું", "આવજો", "બાય",
}  # fmt: skip
_EDGE_PUNCTUATION = " \t\n.,!?।;:\"'`()[]{}<>-–—…"


def clean_text(value: object) -> str | None:
    """A name or a place as it goes in the sheet, or None when it isn't one.

    Keeps the person's own spelling and any ભાઈ or બેન they said; drops filler around it.
    """
    if not isinstance(value, str):
        return None
    raw = [w.strip(_EDGE_PUNCTUATION) for w in value.split()]
    tokens = [w for w in raw if w]
    while tokens and tokens[0].lower() in _LEADING:
        tokens.pop(0)
    while tokens and tokens[-1].lower() in _TRAILING:
        tokens.pop()
    if not tokens or all(w.lower() in _NOT_ANSWERS for w in tokens):
        return None
    text = " ".join(tokens)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT].rsplit(" ", 1)[0]
    return text or None


def clean_note(value: object) -> str | None:
    """Their words for an answer that isn't a number ("નક્કી નહીં"), tidied for the sheet."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip(_EDGE_PUNCTUATION)
    if not text or text.lower() in _NOT_ANSWERS:
        return None
    return text[:MAX_TEXT]


def clean_days(value: object) -> float | None:
    """Every how many days: from twice a day (still 1) to once in two months."""
    number = _as_number(value)
    if number is None or not 0 < number <= 60:
        return None
    return max(1.0, round(number, 1))


MAX_AGE = 120


def clean_age(value: object) -> int | None:
    """An age in whole years, or None when the number can't be one."""
    number = _as_number(value)
    if number is None or not 1 <= round(number) <= MAX_AGE:
        return None
    return round(number)


def clean_minutes(value: object) -> int | None:
    number = _as_number(value)
    if number is None or not 1 <= round(number) <= 1440:
        return None
    return round(number)


def _as_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(to_ascii_digits(value).strip())
        except ValueError:
            return None
    return None


# Written for the sheet and for the ear ------------------------------------------------------------


def water_text(comes: bool) -> str:
    return YES if comes else NO


def frequency_text(days: float | None, note: str | None = None, *, written: bool = False) -> str | None:
    """1 -> રોજ, 2 -> એકાંતરે, 7 -> અઠવાડિયે એક વાર. `written` adds the number for the sheet."""
    if days is None:
        return note
    if days == 1:
        return "રોજ"
    named = {2: "એકાંતરે", 7: "અઠવાડિયે એક વાર", 30: "મહિને એક વાર"}.get(days)  # type: ignore[call-overload]
    every = f"દર {days:g} દિવસે"
    if named is None and not float(days).is_integer():
        per_week = 7 / days
        if abs(per_week - round(per_week)) < 0.05:
            named = f"અઠવાડિયામાં {round(per_week)} વાર"
    if named is None:
        return every
    return f"{named} ({every})" if written else named


_NAMED_DURATIONS = {30: "અડધો કલાક", 45: "પોણો કલાક", 75: "સવા કલાક", 90: "દોઢ કલાક", 150: "અઢી કલાક"}


def duration_text(minutes: int | None, note: str | None = None, *, written: bool = False) -> str | None:
    """30 -> અડધો કલાક, 90 -> દોઢ કલાક, 120 -> 2 કલાક. `written` adds the minutes for the sheet."""
    if minutes is None:
        return note
    if minutes >= 1440:
        return "આખો દિવસ"
    hours, rest = divmod(minutes, 60)
    if minutes in _NAMED_DURATIONS:
        said = _NAMED_DURATIONS[minutes]
    elif hours == 0:
        return f"{minutes} મિનિટ"
    elif rest == 0:
        said = f"{hours} કલાક"
    elif rest == 30:
        said = f"સાડા {hours} કલાક"
    else:
        said = f"{hours} કલાક {rest} મિનિટ"
    return f"{said} ({minutes} મિનિટ)" if written else said


# Reading answers without the LLM ---------------------------------------------------------------

_EN_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "ninety": 90,
}  # fmt: skip


def _tokens(text: str) -> list[str]:
    # "2કલાક" and "3દિવસે" come through as one word: split the number from its unit.
    text = re.sub(r"(\d)(?=[^\d\s.,])", r"\1 ", to_ascii_digits(text))
    return words(text)


def _number(token: str) -> float | None:
    if re.fullmatch(r"\d+(?:\.\d+)?", token):
        return float(token)
    if token in _EN_NUMBERS:
        return float(_EN_NUMBERS[token])
    value = value_of(token)
    return None if value is None else float(value)


# Yes or no: "does water come?"
_AFFIRM = {"હા", "હાં", "હાજી", "હોવે", "હમ્મ", "yes", "yeah", "yep", "haa", "haan", "ha"}
_NEGATE = {"ના", "નહીં", "નહિ", "નથી", "નઈ", "no", "nahi", "nai", "nope", "નો"}
_COMES = {"આવે", "આવેછે", "આવેજ", "comes"}
_YES_NO_EXTRA = {
    "પાણી", "છે", "આવતું", "આવતુ", "આવતો", "આવતી", "તો", "ને", "હોં", "હો", "જી", "ભાઈ", "બેન", "સાહેબ",
    "બિલકુલ", "જરાય", "અમારે", "મારે", "અમારા", "અહીં", "અહિયાં", "ત્યાં", "ઘરે", "ઘરમાં", "નળમાં", "નળ",
    "એ", "બરાબર", "water", "it", "does", "not", "is", "sir", "ji",
}  # fmt: skip


def yes_or_no(text: str, *, strict: bool = False) -> bool | None:
    """True for "હા, આવે છે", False for "ના, નથી આવતું", None when it isn't clear either way.

    `strict`: every word must be one these rules know, so "ના, પણ ક્યારેક આવે" goes to the LLM.
    """
    tokens = _tokens(text)
    if not tokens:
        return None
    if strict and any(t not in _AFFIRM | _NEGATE | _COMES | _YES_NO_EXTRA for t in tokens):
        return None
    yes = any(t in _AFFIRM or t in _COMES for t in tokens)
    no = any(t in _NEGATE for t in tokens)
    if yes == no:  # both ("ના, આવે છે") or neither
        return None
    return yes


# Every how many days.
_DAILY = {"રોજ", "રોજે", "દરરોજ", "રોજેરોજ", "રોજનું", "રોજનો", "daily", "everyday", "ડેઇલી", "ડેલી"}
_ALTERNATE = {"એકાંતરે", "એકાંતરા", "આંતરે", "આંતરા", "alternate", "અલ્ટરનેટ"}
_TIMES = {"વાર", "વખત", "time", "times"}
_SKIPPING = {"છોડીને", "છોડી", "મૂકીને", "મુકીને"}  # "એક દિવસ છોડીને": every other day
_FREQUENCY_EXTRA = {
    "પાણી", "આવે", "આવેછે", "છે", "તો", "દર", "ને", "હોં", "જી", "સાહેબ", "ભાઈ", "બેન", "ફક્ત",
    "બસ", "લગભગ", "every", "once", "a", "in", "comes", "it", "day", "days", "week", "month",
}  # fmt: skip


def days_from(text: str, *, strict: bool = False) -> float | None:
    """Every how many days water comes: "રોજ" 1, "એકાંતરે" 2, "ત્રણ દિવસે" 3, "અઠવાડિયામાં બે વાર" 3.5."""
    tokens = _tokens(text)
    number: float | None = None
    days: float | None = None
    period: float | None = None  # a week or a month, for "twice a week"
    times: float | None = None
    per_day = False  # "દિવસમાં બે વાર": twice a day is still every day
    skipping = False
    for token in tokens:
        if (n := _number(token)) is not None:
            number = n
        elif token in _DAILY:
            days = 1
        elif token in _ALTERNATE:
            days = 2
        elif token.startswith("દિવસ") or token in ("day", "days"):
            if number is not None:
                days, number = number, None
            else:
                per_day = True
        elif token.startswith("અઠવાડિ") or token.startswith("વીક") or token in ("week", "weekly"):
            days = period = 7
        elif token.startswith("મહિન") or token in ("month", "monthly"):
            days = period = 30
        elif token in _TIMES:
            if number is not None:
                times, number = number, None
        elif token in _SKIPPING:
            skipping = True
        elif strict and token not in _FREQUENCY_EXTRA:
            return None
    if days is None and per_day:
        days = 1
    if days is None and number is not None and times is None:
        days, number = number, None  # "બે" to "કેટલા દિવસે?": every two days
    if days is None or (strict and number is not None):  # a number with nothing it counts
        return None
    if skipping:
        days += 1
    if period and times and times > 1:
        days = period / times
    return clean_days(days)


# How long, on a day it comes.
_HALF = {"અડધો", "અડધી", "અડધું", "અડધા", "half"}
_THREE_QUARTERS = {"પોણો", "પોણી", "પોણું"}
_FRACTION_OF = {"સવા": 0.25, "સાડા": 0.5, "પોણા": -0.25}
_WHOLE_DAY = {"આખો", "આખી", "આખું", "ચોવીસ"}
_DURATION_EXTRA = {
    "પાણી", "આવે", "આવેછે", "છે", "તો", "લગભગ", "માંડ", "ફક્ત", "બસ", "જેટલું", "જેટલો", "જેટલી", "સુધી",
    "દિવસમાં", "ચાલે", "ચાલુ", "રહે", "ને", "હોં", "જી", "સાહેબ", "ભાઈ", "બેન", "about", "around", "only",
    "for", "an", "a", "of", "comes", "it",
}  # fmt: skip


def minutes_from(text: str, *, strict: bool = False) -> int | None:
    """How long water runs: "એક કલાક" 60, "અડધો કલાક" 30, "સાડા ત્રણ કલાક" 210, "45 મિનિટ" 45."""
    tokens = _tokens(text)
    total = 0.0
    found = False
    number: float | None = None
    fraction: float | None = None
    whole_day = False
    for token in tokens:
        if (n := _number(token)) is not None:
            number = n
        elif token in _FRACTION_OF:
            fraction = _FRACTION_OF[token]
        elif token in _HALF:
            number = 0.5
        elif token in _THREE_QUARTERS:
            number = 0.75
        elif token == "દોઢ":
            number = 1.5
        elif token == "અઢી":
            number = 2.5
        elif token.startswith("કલાક") or token in ("hour", "hours", "hr", "hrs", "અવર"):
            hours = 1.0 if number is None else number
            total += (hours + fraction if fraction else hours) * 60
            found, number, fraction = True, None, None
        elif token.startswith(("મિનિટ", "મીનીટ", "મિનીટ")) or token in ("minute", "minutes", "min", "mins"):
            if number is None:
                return None
            total += number
            found, number = True, None
        elif token in _WHOLE_DAY:
            whole_day = True
        elif token.startswith("દિવસ") and whole_day:
            total, found = 1440, True
        elif strict and token not in _DURATION_EXTRA:
            return None
    if not found or (strict and (number is not None or fraction is not None)):
        return None
    if strict and total <= 2:  # "એક મિનિટ" alone is usually "hold on": the LLM decides
        return None
    return clean_minutes(total)


# How old.
_YEARS = {
    "વર્ષ", "વરસ", "વર્ષની", "વર્ષનો", "વર્ષના", "વર્ષનાં", "વરસની", "વરસનો", "વરસના", "સાલ",
    "years", "year", "yrs",
}  # fmt: skip
_AGE_EXTRA = {
    "મારી", "મારે", "મને", "ઉંમર", "ઉમર", "છે", "છું", "થયા", "થયાં", "થઈ", "હું", "તો", "જી", "સાહેબ", "ભાઈ", "બેન",
    "લગભગ", "my", "age", "is", "i", "am", "old", "about", "around",
}  # fmt: skip
# "એક મિનિટ" (hold on) and "બે દિવસે" carry a number that isn't an age.
_NOT_AGE_UNITS = (
    "મિનિટ", "મીનીટ", "મિનીટ", "કલાક", "દિવસ", "અઠવાડિ", "મહિન", "minute", "hour", "day", "week",
)  # fmt: skip


def age_from(text: str, *, strict: bool = False) -> int | None:
    """How old: "45", "પિસ્તાલીસ વર્ષ", "મારી ઉંમર 62 છે". One number only: "40-45" goes to the LLM.

    `strict`: every word must be one these rules know.
    """
    numbers = []
    for token in _tokens(text):
        if (n := _number(token)) is not None:
            numbers.append(n)
        elif token.startswith(_NOT_AGE_UNITS):
            return None
        elif token in _YEARS:
            continue
        elif strict and token not in _AGE_EXTRA:
            return None
    if len(numbers) != 1:
        return None
    return clean_age(numbers[0])


# What else a turn can be ---------------------------------------------------------------------------

_REPEAT_ASKS = {"શું", "શુ", "ફરીથી", "ફરી", "સંભળાયું", "સમજાયું", "હેં", "what", "repeat", "again", "pardon"}
_REPEAT_EXTRA = {"બોલો", "બોલજો", "કહો", "કહેશો", "નહીં", "નથી", "જરા", "એ", "sorry", "say", "please", "તો"}


def asks_to_repeat(text: str) -> bool:
    """ "શું?", "ફરીથી બોલો", "સંભળાયું નહીં": the question again, not an answer."""
    tokens = _tokens(text)
    return (
        bool(tokens)
        and any(t in _REPEAT_ASKS for t in tokens)
        and all(t in _REPEAT_ASKS | _REPEAT_EXTRA for t in tokens)
    )


def is_busy(text: str) -> bool:
    """ "હું બિઝી છું", "પછી ફોન કરજો", "અત્યારે ટાઈમ નથી"."""
    tokens = set(_tokens(text))
    if tokens & {"busy", "બિઝી", "બીઝી", "કામમાં"}:
        return True
    later = "પછી" in tokens and bool(tokens & {"ફોન", "કોલ", "કૉલ", "વાત"})
    no_time = bool(tokens & {"ટાઈમ", "ટાઇમ", "સમય", "time"}) and bool(tokens & {"નથી", "નહીં", "no", "not"})
    return later or no_time


_SAYS_WRONG = {"નહીં", "નહિ", "નઈ", "ખોટું", "ખોટુ", "ખોટો", "ખોટી", "ગલત", "not", "wrong", "galat"}


def says_its_wrong(text: str) -> bool:
    """ "ના, ગામ ખાંભા નહીં, ખંભાળિયા", "નામ ખોટું લખ્યું": the words of a correction."""
    tokens = _tokens(text)
    return bool(tokens) and (tokens[0] in {"ના", "no", "na", "nahi"} or any(t in _SAYS_WRONG for t in tokens))


def says_goodbye(text: str) -> bool:
    tokens = _tokens(text)
    if any(t in {"આવજો", "બાય", "bye", "goodbye"} for t in tokens):
        return True
    hang_up = {"મૂકું", "મુકું", "રાખું", "મૂકો", "મુકો"}
    return any(a == "ફોન" and b in hang_up for a, b in zip(tokens, tokens[1:], strict=False))
