"""What a Gujarati caller means, read from their words: which day, and whether they're done.

The agent reads the same Latin words it always did: speech-to-text writes code-mixed speech with
English words in English ("મને tomorrow call કરજો"), and those go on to the English logic untouched.
"""

from __future__ import annotations

import re

from agent.gujarati.numbers import MONTHS, to_ascii_digits, value_of

_WORD = re.compile(r"[^\s,.!?।;:\"'()\-–—…]+")


def words(text: str) -> list[str]:
    """Split on spaces and punctuation, keeping vowel signs and the virama inside their word."""
    return _WORD.findall(text.lower().replace("’", "'"))


def has_gujarati(text: str) -> bool:
    return any("\u0a80" <= ch <= "\u0aff" for ch in text)


# Days ----------------------------------------------------------------------------------------

_WEEKDAY_STEMS = {
    "સોમવાર": "monday", "મંગળવાર": "tuesday", "બુધવાર": "wednesday", "ગુરુવાર": "thursday",
    "ગુરૂવાર": "thursday", "શુક્રવાર": "friday", "શનિવાર": "saturday", "રવિવાર": "sunday",
}  # fmt: skip
_MONTH_KEYS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MONTH_STEMS = dict(zip(MONTHS, _MONTH_KEYS, strict=True)) | {
    "જાન્યુ": "jan", "ફેબ્રુ": "feb", "ઓગસ્ટ": "aug", "ઑગષ્ટ": "aug", "ઓગષ્ટ": "aug", "સપ્ટે": "sep",
    "ઓક્ટોબર": "oct", "ઑક્ટો": "oct", "ઓક્ટો": "oct", "નવે": "nov", "ડિસે": "dec", "ડીસેમ્બર": "dec",
}  # fmt: skip
_TODAY = {"આજે", "આજ", "આજનું", "આજની", "આજના"}
# "કાલે" means yesterday as well as tomorrow. Nobody books a table for yesterday, so it's tomorrow
# here; "ગઈકાલે" (only ever yesterday) isn't listed and falls through to asking which day.
_TOMORROW = {"કાલે", "કાલ", "કાલનું", "કાલની", "કાલના", "આવતીકાલે", "આવતીકાલ", "આવતી", "કાલ્ય"}
_NEXT = {"આવતા", "આવતે", "આવતો", "આગામી", "આવનારા"}
_DAY_AFTER_TOMORROW = {"પરમ", "પરમદિવસે", "પરમદિ", "પરમદહાડે"}
_DATE_WORDS = {"તારીખે", "તારીખ", "તારીખનું", "તા"}


def day_words(said: str) -> str:
    """A day in Gujarati as the English words resolve_day reads: "આવતા મંગળવારે" -> "next tuesday".

    Latin words pass through, so "Sunday" and a code-mixed "tomorrow સાંજે" need nothing here.
    """
    tokens = words(to_ascii_digits(said))
    out: list[str] = []
    for i, token in enumerate(tokens):
        following = tokens[i + 1] if i + 1 < len(tokens) else ""
        ordinal = re.fullmatch(r"(\d{1,2})(?:મી|મીએ|ની|એ)", token)
        if ordinal:
            out.append(f"{ordinal.group(1)}th")
        elif token.isdigit() and following in _DATE_WORDS:
            out.append(f"{token}th")
        elif token in _TODAY:
            out.append("today")
        elif token in _TOMORROW:
            out.append("tomorrow")
        elif token in _DAY_AFTER_TOMORROW:
            out.append("overmorrow")
        elif token in _NEXT:
            out.append("next")
        elif (
            weekday := next((v for k, v in _WEEKDAY_STEMS.items() if token.startswith(k)), None)
        ) is not None:
            out.append(weekday)
        elif (month := next((v for k, v in _MONTH_STEMS.items() if token.startswith(k)), None)) is not None:
            out.append(month)
        elif (value := value_of(token)) is not None and 1 <= value <= 31 and following in _DATE_WORDS:
            out.append(f"{value}th")
        elif (value := value_of(token)) is not None and 1 <= value <= 31 and _is_month(following):
            out.append(str(value))
        elif token.isascii():
            out.append(token)
    return " ".join(out)


def _is_month(token: str) -> bool:
    return any(token.startswith(stem) for stem in _MONTH_STEMS)


# Goodbyes ------------------------------------------------------------------------------------

# Clear enough to hang up on by themselves.
_FAREWELLS = {"આવજો", "આવજે", "બાય", "ટાટા"}
_FAREWELL_PHRASES = (("ફોન", "મૂકું"), ("ફોન", "મુકું"), ("ફોન", "રાખું"), ("રાખું", "છું"), ("મૂકું", "છું"))
# A goodbye only when the call is winding up. "જય શ્રી કૃષ્ણ" opens a call as readily as it closes
# one, so on its own it must never hang up.
_THANKS = {"આભાર", "ધન્યવાદ", "થેંક", "થેન્ક", "થેંક્સ", "થેન્ક્સ", "થેંક્યુ", "થેન્ક્યુ", "thank", "thanks"}
_NOTHING_MORE = {"ના", "નહીં", "નહિ", "નથી", "બસ", "કંઈ", "કાંઈ", "કશું"}
_PARTING_GREETINGS = {"જય", "નમસ્તે", "નમસ્કાર", "સલામ"}

# Every word of a turn that does nothing but wind the call up.
_CLOSING_WORDS = (
    _FAREWELLS | _THANKS | _NOTHING_MORE | _PARTING_GREETINGS | {
        "હોં", "હો", "હા", "ઠીક", "છે", "સારું", "બરાબર", "ભલે", "ઓકે", "ચાલો", "ચાલ", "તો", "પછી", "બીજું",
        "જ", "એટલું", "એટલુંજ", "હમણાં", "અત્યારે", "ફોન", "મૂકું", "મુકું", "રાખું", "છું", "મળીએ", "શ્રી",
        "કૃષ્ણ", "જિનેન્દ્ર", "સ્વામિનારાયણ", "યુ", "તમારો", "ખૂબ", "બહુ", "ભાઈ", "બેન", "સાહેબ", "જી",
        "ઘણો", "ખુબ", "no", "thanks", "thank", "you", "bye", "ok", "okay",
    }
)  # fmt: skip
_ASKED_ANYTHING_ELSE = re.compile(r"બીજું\s*(?:કંઈ|કાંઈ|કશું)|બીજી\s*કોઈ|બીજો\s*કોઈ|બીજું\s*શું")


def _has_farewell(tokens: list[str]) -> bool:
    if any(token in _FAREWELLS for token in tokens):
        return True
    return any(pair in _FAREWELL_PHRASES for pair in zip(tokens, tokens[1:], strict=False))


def asked_anything_else(agent_line: str) -> bool:
    return bool(_ASKED_ANYTHING_ELSE.search(agent_line))


def is_done(caller_words: str, agent_line: str) -> bool:
    """Whether end_call may hang up: a goodbye or thanks, or "ના, બસ" to "બીજું કંઈ?"."""
    tokens = words(caller_words)
    if _has_farewell(tokens) or any(token in _THANKS for token in tokens):
        return True
    return asked_anything_else(agent_line) and bool(tokens) and tokens[0] in _NOTHING_MORE


def closes_the_call(caller_words: str, agent_line: str) -> bool:
    """Whether the whole turn is a goodbye, clear enough to hang up without asking the LLM."""
    tokens = words(caller_words)
    if not tokens or any(token not in _CLOSING_WORDS for token in tokens):
        return False
    if _has_farewell(tokens):
        return True
    return asked_anything_else(agent_line) and is_winding_up(tokens)


def is_winding_up(tokens: list[str]) -> bool:
    return any(token in _NOTHING_MORE | _THANKS | _PARTING_GREETINGS for token in tokens)
