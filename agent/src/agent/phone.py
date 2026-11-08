"""Phone numbers from the sheet, as the phone network wants them (E.164) and as people read them.

A sheet holds numbers however someone typed or pasted them: "98765 43210", "+91-98765-43210",
"09876543210", Gujarati digits, or "9.87654E+09" when a spreadsheet decided the column was numeric.
"""

from __future__ import annotations

import os
import re

from agent.gujarati.numbers import spoken_number_text

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
}  # fmt: skip
_REPEATS = {"double": 2, "triple": 3}
_SCIENTIFIC = re.compile(r"^\s*\d(?:\.\d+)?[eE]\+?\d+\s*$")


def default_country_code() -> str:
    return (os.getenv("DEFAULT_COUNTRY_CODE") or "91").lstrip("+")


def digits_of(text: str) -> str:
    """Every digit in `text`, including Gujarati digits and digits written as words ("ડબલ પાંચ")."""
    digits: list[str] = []
    repeat = 1
    for token in re.findall(r"\d+|[a-z]+", spoken_number_text(text).lower()):
        if token in _REPEATS:
            repeat = _REPEATS[token]
            continue
        found = token if token.isdigit() else _DIGIT_WORDS.get(token)
        if found is None or (token in ("oh", "o") and not digits):  # "Oh, it's..." isn't a zero
            repeat = 1
            continue
        digits.append(found[0] * repeat + found[1:])
        repeat = 1
    return "".join(digits)


def normalize_phone(raw: str, country_code: str | None = None) -> str | None:
    """A number as E.164 ("+919876543210"), or None if it can't be one. Ten digits get the default
    country code (DEFAULT_COUNTRY_CODE, 91 for India)."""
    code = country_code or default_country_code()
    text = str(raw).strip()
    if _SCIENTIFIC.match(text):  # 9.87654321E+09 from a cell formatted as a number
        text = str(int(float(text)))
    digits = digits_of(text)
    if text.startswith("+"):
        return f"+{digits}" if 8 <= len(digits) <= 15 else None
    if text.startswith("00") and 10 <= len(digits) - 2 <= 15:  # 0091 98765 43210
        return f"+{digits[2:]}"
    if len(digits) == 10:
        return f"+{code}{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"+{code}{digits[1:]}"
    if 11 <= len(digits) <= 15:
        return f"+{digits}"
    return None


def pretty(e164: str) -> str:
    """For people: +91 98765 43210."""
    digits = e164.lstrip("+")
    if digits.startswith("91") and len(digits) == 12:
        return f"+91 {digits[2:7]} {digits[7:]}"
    if digits.startswith("1") and len(digits) == 11:
        return f"+1 {digits[1:4]} {digits[4:7]} {digits[7:]}"
    return e164


def masked(e164: str | None) -> str:
    """For logs: enough to tell calls apart, not enough to dial: +9198xxxxx210."""
    if not e164:
        return "-"
    digits = e164.lstrip("+")
    if len(digits) < 7:
        return "x" * len(digits)
    return f"+{digits[:4]}{'x' * (len(digits) - 7)}{digits[-3:]}"
