"""Scoring speech-to-text on Gujarati: word and character error rates, and the words that matter.

WER alone misleads here. "ઓફિસ" and "office" are the same word in two scripts, and "૯૮" and "98" the
same number, but a plain comparison counts each as an error. So both sides are normalised first, and
the words a booking depends on (names, digits) get their own score: an agent that gets every filler
word right but mishears "જિજ્ઞા" has failed.
"""

from __future__ import annotations

import re
import unicodedata

from agent.gujarati.numbers import to_ascii_digits
from agent.speakable import spoken_digits

_PUNCTUATION = re.compile(r"[.,!?।;:\"'()\-–—…]")

# The same loanword, written the two ways speech-to-text might. Extend this from real output.
SAME_WORD = {
    "ઓફિસ": "office", "ઑફિસ": "office", "બિઝનેસ": "business", "બિઝનસ": "business", "બિઝી": "busy",
    "કોલ": "call", "કૉલ": "call", "એડ્રેસ": "address", "એડ્રેસ્સ": "address", "વોટ્સએપ": "whatsapp",
    "વૉટ્સઍપ": "whatsapp", "વોટ્સેપ": "whatsapp", "ટેબલ": "table", "બુક": "book", "બુકિંગ": "booking",
    "કન્ફર્મ": "confirm", "ઓનલાઇન": "online", "પેમેન્ટ": "payment", "પાર્કિંગ": "parking", "ટુમોરો": "tomorrow",
    "ટુનાઇટ": "tonight", "પ્લાન": "plan", "ચેન્જ": "change", "હોલ્ડ": "hold", "સેટરડે": "saturday",
    "અવેલેબલ": "available", "એક્ચ્યુઅલી": "actually",
}  # fmt: skip


def normalise(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", to_ascii_digits(text)).lower()
    text = text.replace("‌", "").replace("‍", "").replace("થઇ", "થઈ")
    return [SAME_WORD.get(word, word) for word in _PUNCTUATION.sub(" ", text).split()]


def _edit_distance(reference: list[str] | str, hypothesis: list[str] | str) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, ref in enumerate(reference, 1):
        current = [i]
        for j, hyp in enumerate(hypothesis, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ref != hyp)))
        previous = current
    return previous[-1]


def word_errors(reference: str, hypothesis: str) -> tuple[int, int]:
    """(errors, reference words): sum these across a test set before dividing."""
    ref = normalise(reference)
    return _edit_distance(ref, normalise(hypothesis)), len(ref)


def char_errors(reference: str, hypothesis: str) -> tuple[int, int]:
    """Character error rate suits Gujarati, where a suffix error shouldn't cost the whole word."""
    ref, hyp = " ".join(normalise(reference)), " ".join(normalise(hypothesis))
    return _edit_distance(ref, hyp), len(ref)


def kept_words(keep: list[str], hypothesis: str) -> tuple[int, int]:
    """(heard, wanted): how many of the words that matter came through."""
    heard = normalise(hypothesis)
    joined = " ".join(heard)
    found = sum(1 for word in keep if any(part in joined for part in normalise(word)))
    return found, len(keep)


def digits_match(expected: str, hypothesis: str) -> bool:
    return spoken_digits(hypothesis) == re.sub(r"\D", "", expected)
