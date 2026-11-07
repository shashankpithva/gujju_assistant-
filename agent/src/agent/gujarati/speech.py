"""The last step before the voice: LLM text turned into what a Gujarati speaker would say aloud.

The transcript keeps what the LLM wrote; only the voice gets this version. Each step removes a way
the voice could slip out of Gujarati: "7:30 PM" and "380" read in English, a brand name mangled, or
a sentence whose verb doesn't match the voice's gender.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterable, AsyncIterator, Callable

from agent.gujarati.lines import Gender
from agent.gujarati.numbers import clock_words, day_part, number_words, to_ascii_digits

_DIGIT_WORDS = ["શૂન્ય", "એક", "બે", "ત્રણ", "ચાર", "પાંચ", "છ", "સાત", "આઠ", "નવ"]

# Names the voice should say the Gujarati way. Sarvam reads Latin text inside a Gujarati sentence,
# but a Gujarati spelling keeps the accent in one voice. Extend it from listening tests.
LEXICON = {
    "whatsapp": "વૉટ્સઍપ",
    "swiggy": "સ્વિગી",
    "zomato": "ઝોમેટો",
    "google": "ગૂગલ",
    "ok": "ઓકે",
    "okay": "ઓકે",
    "ai": "એઆઈ",
    "the saffron table": "ધ સેફ્રોન ટેબલ",
}
_LEXICON = re.compile(
    r"(?<![A-Za-z])("
    + "|".join(re.escape(k) for k in sorted(LEXICON, key=len, reverse=True))
    + r")(?![A-Za-z])",
    re.IGNORECASE,
)

# First-person verbs that show the speaker's gender. Only forms that can't refer to anyone else:
# "થઈ ગઈ" stays, as it may be about a table. The voice and the grammar must agree on every call.
_FEMININE_TO_MASCULINE = {
    "સમજી ગઈ": "સમજી ગયો",
    "રહી છું": "રહ્યો છું",
    "ગઈ છું": "ગયો છું",
    "બેઠી છું": "બેઠો છું",
}
_MASCULINE_TO_FEMININE = {v: k for k, v in _FEMININE_TO_MASCULINE.items()}

_TIME = re.compile(
    r"(?<![\d:.])(\d{1,2})(?:[:.]([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?)(?![A-Za-z])"  # 7:30 PM, 7 pm
    r"|(?<![\d:.])(\d{1,2})[:]([0-5]\d)(?![\d:])",  # 7:30
    re.IGNORECASE,
)
_RUPEES_BEFORE = re.compile(r"(?:₹|\bRs\.?|\bINR|રૂ\.)\s?(\d[\d,]*)", re.IGNORECASE)
_LONG_NUMBER = re.compile(r"\+?\d[\d \-]{5,}\d")
_NUMBER = re.compile(r"\d[\d,]*")
_RANGE = re.compile(r"(?<![\d-])(\d{1,4})\s*[–—-]\s*(\d{1,4})(?![\d-])")  # "12-3", not a phone number
# The full stop in "રૂ. 380" and "Rs. 380" doesn't end a sentence.
_SENTENCE_DONE = re.compile(r".*(?<!રૂ)(?<!Rs)[.?!]\s+", re.DOTALL)


def _say_time(match: re.Match[str], text: str) -> str:
    hour_s, minute_s, meridiem, plain_hour, plain_minute = match.groups()
    hour = int(hour_s or plain_hour)
    minute = int(minute_s or plain_minute or 0)
    if hour > 23:
        return match.group(0)
    words = clock_words(hour, minute)
    if meridiem:
        hour24 = hour % 12 + (12 if meridiem.lower().startswith("p") else 0)
        words = f"{day_part(hour24)} {words}"
    # Already followed by "વાગ્યે": don't say it twice.
    return words if text[match.end() :].lstrip().startswith("વાગ") else f"{words} વાગ્યે"


def _say_digits_one_by_one(match: re.Match[str]) -> str:
    text = match.group(0)
    groups = [g for g in re.split(r"[ \-]+", text.lstrip("+")) if g]
    digits = "".join(groups)
    if len(digits) < 7:  # prices and years stay numbers
        return text
    if len(groups) == 1 and len(digits) == 10:  # 9876543210 -> 98765 43210
        groups = [digits[:5], digits[5:]]
    return ", ".join(" ".join(_DIGIT_WORDS[int(d)] for d in group) for group in groups)


def _say_number(match: re.Match[str]) -> str:
    return number_words(int(match.group(0).replace(",", "")))


def for_the_ear(text: str, gender: Gender = "male") -> str:
    """One whole sentence or more, as the voice should say it."""
    text = to_ascii_digits(text).replace("।", ".")
    text = _LONG_NUMBER.sub(_say_digits_one_by_one, text)  # first: a hyphen here isn't a range
    text = _TIME.sub(lambda m: _say_time(m, text), text)
    text = _RUPEES_BEFORE.sub(r"\1 રૂપિયા", text)
    text = _RANGE.sub(r"\1 થી \2", text)
    text = _NUMBER.sub(_say_number, text)
    text = _LEXICON.sub(lambda m: LEXICON[m.group(1).lower()], text)
    fixes = _FEMININE_TO_MASCULINE if gender == "male" else _MASCULINE_TO_FEMININE
    for wrong, right in fixes.items():
        text = text.replace(wrong, right)
    return text


def speak_gujarati(gender: Gender) -> Callable[[AsyncIterable[str]], AsyncIterator[str]]:
    """TTS text transform: for_the_ear on each finished sentence.

    The voice starts on whole sentences anyway, so holding text back until a sentence ends costs no
    time, and a time or number split across two chunks ("7:" then "30 PM") stays in one piece.
    """

    async def transform(chunks: AsyncIterable[str]) -> AsyncIterator[str]:
        buffer = ""
        async for chunk in chunks:
            buffer += chunk
            done = _SENTENCE_DONE.match(buffer)
            if done:
                yield for_the_ear(done.group(0), gender)
                buffer = buffer[done.end() :]
        if buffer:
            yield for_the_ear(buffer, gender)

    return transform
