"""Numbers, times, dates, phone numbers and booking codes the way Gujarati speakers say them.

A Gujarati caller says "સાંજે સાડા સાત વાગ્યે", not "7:30 PM", and every number from 1 to 99 is a word
of its own. Spelling these out here means the voice can't read a time or a price in English.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

# 0 to 99. Spellings vary between writers, so VARIANTS below also lists the common alternatives.
_WORDS = [
    "શૂન્ય",
    "એક",
    "બે",
    "ત્રણ",
    "ચાર",
    "પાંચ",
    "છ",
    "સાત",
    "આઠ",
    "નવ",
    "દસ",
    "અગિયાર",
    "બાર",
    "તેર",
    "ચૌદ",
    "પંદર",
    "સોળ",
    "સત્તર",
    "અઢાર",
    "ઓગણીસ",
    "વીસ",
    "એકવીસ",
    "બાવીસ",
    "ત્રેવીસ",
    "ચોવીસ",
    "પચ્ચીસ",
    "છવ્વીસ",
    "સત્તાવીસ",
    "અઠ્ઠાવીસ",
    "ઓગણત્રીસ",
    "ત્રીસ",
    "એકત્રીસ",
    "બત્રીસ",
    "તેત્રીસ",
    "ચોત્રીસ",
    "પાંત્રીસ",
    "છત્રીસ",
    "સાડત્રીસ",
    "આડત્રીસ",
    "ઓગણચાલીસ",
    "ચાલીસ",
    "એકતાલીસ",
    "બેતાલીસ",
    "તેતાલીસ",
    "ચુંમાલીસ",
    "પિસ્તાલીસ",
    "છેતાલીસ",
    "સુડતાલીસ",
    "અડતાલીસ",
    "ઓગણપચાસ",
    "પચાસ",
    "એકાવન",
    "બાવન",
    "ત્રેપન",
    "ચોપન",
    "પંચાવન",
    "છપ્પન",
    "સત્તાવન",
    "અઠ્ઠાવન",
    "ઓગણસાઠ",
    "સાઠ",
    "એકસઠ",
    "બાસઠ",
    "ત્રેસઠ",
    "ચોસઠ",
    "પાંસઠ",
    "છાસઠ",
    "સડસઠ",
    "અડસઠ",
    "ઓગણસિત્તેર",
    "સિત્તેર",
    "એકોતેર",
    "બોતેર",
    "તોતેર",
    "ચુંમોતેર",
    "પંચોતેર",
    "છોતેર",
    "સિત્યોતેર",
    "ઇઠ્યોતેર",
    "ઓગણએંસી",
    "એંસી",
    "એક્યાસી",
    "બ્યાસી",
    "ત્યાસી",
    "ચોર્યાસી",
    "પંચાસી",
    "છ્યાસી",
    "સિત્યાસી",
    "અઠ્યાસી",
    "નેવ્યાસી",
    "નેવું",
    "એકાણું",
    "બાણું",
    "ત્રાણું",
    "ચોરાણું",
    "પંચાણું",
    "છન્નું",
    "સત્તાણું",
    "અઠ્ઠાણું",
    "નવ્વાણું",
]

VARIANTS = {
    "અગ્યાર": 11, "પંદરા": 15, "સતર": 17, "ઓગણિસ": 19, "પચીસ": 25, "છવીસ": 26, "સત્યાવીસ": 27,
    "અઠ્યાવીસ": 28, "ઓગણત્રિસ": 29, "ચુમાલીસ": 44, "પીસ્તાલીસ": 45, "છેંતાલીસ": 46, "ઓગણપચ્ચાસ": 49,
    "ચોપ્પન": 54, "સત્યાવન": 57, "અઠ્યાવન": 58, "ઓગણસિતેર": 69, "સીતેર": 70, "સિતેર": 70, "એકોતેરે": 71,
    "ચુમોતેર": 74, "ઓગણ્યાએંસી": 79, "ઓગણાએંસી": 79, "એસી": 80, "નેવુ": 90, "નેવું": 90, "છન્નુ": 96,
    "અઠ્ઠાણુ": 98, "નવ્વાણુ": 99, "નવાણું": 99, "ઝીરો": 0, "મીંડું": 0, "મીંડુ": 0, "શુન્ય": 0,
}  # fmt: skip

# How many callers read a number out, in English words written in Gujarati by the speech-to-text.
_ENGLISH_DIGITS = {
    "વન": 1, "ટુ": 2, "થ્રી": 3, "ફોર": 4, "ફાઇવ": 5, "ફાઈવ": 5, "સિક્સ": 6, "સેવન": 7, "એઇટ": 8,
    "એઈટ": 8, "નાઇન": 9, "નાઈન": 9, "ટેન": 10,
}  # fmt: skip
_REPEATS = {"ડબલ": "double", "ડબ્બલ": "double", "ટ્રિપલ": "triple", "ત્રિપલ": "triple"}

_VALUE = {word: n for n, word in enumerate(_WORDS)} | VARIANTS | _ENGLISH_DIGITS

_HUNDREDS = {
    "સો": 100, "બસો": 200, "ત્રણસો": 300, "ચારસો": 400, "પાંચસો": 500, "છસો": 600, "સાતસો": 700,
    "આઠસો": 800, "નવસો": 900, "દોઢસો": 150, "અઢીસો": 250,
}  # fmt: skip

_ASCII_DIGITS = str.maketrans("૦૧૨૩૪૫૬૭૮૯", "0123456789")
_NUMBER_WORD_SUFFIXES = ("માં", "નું", "ની", "ના", "નો")


def to_ascii_digits(text: str) -> str:
    """૯૮૭ -> 987. Speech-to-text may write either; the API and the phone format need ASCII."""
    return text.translate(_ASCII_DIGITS)


def number_words(n: int) -> str:
    """380 -> ત્રણસો એંસી, 1200 -> બારસો, 1250 -> એક હજાર બસો પચાસ."""
    if n < 0:
        return f"માઇનસ {number_words(-n)}"
    if n < 100:
        return _WORDS[n]
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        head = "સો" if hundreds == 1 else "બસો" if hundreds == 2 else f"{_WORDS[hundreds]}સો"
        return head if rest == 0 else f"{head} {_WORDS[rest]}"
    if n < 100_000:
        thousands, rest = divmod(n, 1000)
        # "બારસો" is how a price is said; "એક હજાર બસો પચાસ" takes over once tens are involved.
        if rest and rest % 100 == 0 and thousands < 10:
            return f"{_WORDS[n // 100]}સો"
        head = f"{_WORDS[thousands]} હજાર"
        return head if rest == 0 else f"{head} {number_words(rest)}"
    lakhs, rest = divmod(n, 100_000)
    head = f"{number_words(lakhs)} લાખ"
    return head if rest == 0 else f"{head} {number_words(rest)}"


def value_of(token: str) -> int | None:
    if token in _VALUE:
        return _VALUE[token]
    if token in _HUNDREDS:
        return _HUNDREDS[token]
    if token.endswith("સો") and token[:-2] in _VALUE:  # "બારસો", "પંદરસો"
        return _VALUE[token[:-2]] * 100
    for suffix in _NUMBER_WORD_SUFFIXES:  # "ચારનું", "ત્રણસોમાં"
        stem = token.removesuffix(suffix)
        if stem != token and (value := value_of(stem)) is not None:
            return value
    return None


_TOKEN = re.compile(r"[^\s,.!?।;:\"'()\-–—…]+")


def spoken_number_text(text: str) -> str:
    """Gujarati digits and number words as ASCII digits, for the digit reader in speakable.py.

    "નવ આઠ સાત", "અઠ્ઠાણું છોતેર" and "ડબલ પાંચ" become "9 8 7", "98 76" and "double 5". Anything else
    is left for the English reader, which ignores what it doesn't know.
    """
    text = to_ascii_digits(text)

    def swap(match: re.Match[str]) -> str:
        token = match.group(0)
        if token in _REPEATS:
            return _REPEATS[token]
        value = _VALUE.get(token)
        return token if value is None else str(value)

    return _TOKEN.sub(swap, text)


# "સાડા ત્રણસો" is three and a half hundreds: the word adds a part of the unit, it doesn't multiply.
_FRACTIONS = {"સવા": 0.25, "સાડા": 0.5, "પોણા": -0.25}


def amounts_in(text: str) -> set[int]:
    """Rupee amounts said in Gujarati words: "ત્રણસો એંસી રૂપિયા", "સાડા ત્રણસો રૂપિયા", "બારસો રૂપિયા"."""
    tokens = _TOKEN.findall(to_ascii_digits(text))
    amounts = set()
    for i, token in enumerate(tokens):
        # Not just "રૂ...": "બે રૂમ" is two rooms.
        if not (token.startswith("રૂપિય") or token in ("રૂ", "rs", "rupee", "rupees")):
            continue
        total, start = 0, i
        while start > 0:
            word = tokens[start - 1]
            if word == "હજાર":
                unit = value_of(tokens[start - 2]) if start >= 2 else None
                total += (unit or 1) * 1000
                start -= 2 if unit is not None else 1
            elif (value := value_of(word)) is not None:
                total += value
                start -= 1
            else:
                break
        if total >= 100 and start > 0 and tokens[start - 1] in _FRACTIONS:
            unit = 1000 if total >= 1000 else 100
            total += round(unit * _FRACTIONS[tokens[start - 1]])
        if total:
            amounts.add(total)
    return amounts


# Times ---------------------------------------------------------------------------------------


def day_part(hour: int) -> str:
    """સવારે, બપોરે, સાંજે or રાત્રે, by the hour of the day."""
    if 4 <= hour < 12:
        return "સવારે"
    if 12 <= hour < 16:
        return "બપોરે"
    if 16 <= hour < 20:
        return "સાંજે"
    return "રાત્રે"


def clock_words(hour: int, minute: int) -> str:
    """The time without "વાગ્યે": સાડા સાત, સવા આઠ, પોણા નવ, and the special દોઢ (1:30) and અઢી (2:30)."""
    twelve = hour % 12 or 12
    if minute == 0:
        return _WORDS[twelve]
    if minute == 15:
        return f"સવા {_WORDS[twelve]}"
    if minute == 30:
        return {1: "દોઢ", 2: "અઢી"}.get(twelve, f"સાડા {_WORDS[twelve]}")
    if minute == 45:
        return f"પોણા {_WORDS[twelve % 12 + 1]}"
    return f"{_WORDS[twelve]} ને {_WORDS[minute]}"


def speak_time(t: datetime | time) -> str:
    """19:30 -> સાંજે સાડા સાત વાગ્યે."""
    return f"{day_part(t.hour)} {clock_words(t.hour, t.minute)} વાગ્યે"


def join_or(items: list[str]) -> str:
    """a; a કે b; a, b કે c."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} કે {items[-1]}"


def join_times(times: list[datetime]) -> str:
    """Alternatives said the short way when they share a part of the day: રાત્રે આઠ, સવા આઠ કે નવ વાગ્યે."""
    parts = {day_part(t.hour) for t in times}
    if len(parts) == 1:
        return f"{parts.pop()} {join_or([clock_words(t.hour, t.minute) for t in times])} વાગ્યે"
    return join_or([speak_time(t) for t in times])


# Days ----------------------------------------------------------------------------------------

_WEEKDAYS = ("સોમવાર", "મંગળવાર", "બુધવાર", "ગુરુવાર", "શુક્રવાર", "શનિવાર", "રવિવાર")
MONTHS = (
    "જાન્યુઆરી", "ફેબ્રુઆરી", "માર્ચ", "એપ્રિલ", "મે", "જૂન", "જુલાઈ", "ઑગસ્ટ", "સપ્ટેમ્બર", "ઑક્ટોબર",
    "નવેમ્બર", "ડિસેમ્બર",
)  # fmt: skip


def _on(word: str) -> str:
    """ "on": a vowel sign after a consonant (ડિસેમ્બરે), a whole vowel after a vowel (જાન્યુઆરીએ, મેએ)."""
    return f"{word}એ" if word[-1] in "ીઈે" else f"{word}ે"


def speak_day(d: date, today: date) -> str:
    """આજે, આવતીકાલે, શનિવારે, or શુક્રવારે, પચ્ચીસ ડિસેમ્બરે more than two weeks out."""
    if d == today:
        return "આજે"
    if d == today + timedelta(days=1):
        return "આવતીકાલે"
    weekday = _on(_WEEKDAYS[d.weekday()])
    if d - today < timedelta(days=7):
        return weekday
    if d - today < timedelta(days=14):
        return f"{weekday}, {_WORDS[d.day]} તારીખે"
    return f"{weekday}, {_WORDS[d.day]} {_on(MONTHS[d.month - 1])}"


# Phone numbers and booking codes ---------------------------------------------------------------


def speak_digits(digits: str) -> str:
    """Digits one by one in groups of three, like speakable.speak_digits: એક બે ત્રણ, ચાર પાંચ છ."""
    groups = [digits[i : i + 3] for i in range(0, len(digits), 3)]
    return ", ".join(" ".join(_WORDS[int(d)] for d in group) for group in groups)


def speak_phone(e164: str) -> str:
    """+919876543210 -> નવ આઠ સાત છ પાંચ, ચાર ત્રણ બે એક શૂન્ય."""
    digits = e164.lstrip("+")
    if digits.startswith("91") and len(digits) == 12:
        groups = [digits[2:7], digits[7:]]
    else:
        groups = [digits[i : i + 3] for i in range(0, len(digits), 3)]
    return ", ".join(" ".join(_WORDS[int(d)] for d in group) for group in groups)


# How letters are said in Gujarati. Written out, so the voice reads each one and never tries a word.
_LETTERS = {
    "A": "એ", "B": "બી", "C": "સી", "D": "ડી", "E": "ઈ", "F": "એફ", "G": "જી", "H": "એચ", "I": "આઈ",
    "J": "જે", "K": "કે", "L": "એલ", "M": "એમ", "N": "એન", "O": "ઓ", "P": "પી", "Q": "ક્યૂ", "R": "આર",
    "S": "એસ", "T": "ટી", "U": "યૂ", "V": "વી", "W": "ડબલ્યૂ", "X": "એક્સ", "Y": "વાય", "Z": "ઝેડ",
}  # fmt: skip
_LETTER_OF = {spoken: letter for letter, spoken in _LETTERS.items()} | {"ક્યુ": "Q", "યુ": "U", "ડબલ્યુ": "W"}


def spell_code(code: str) -> str:
    """K7Q2 -> કે, સાત, ક્યૂ, બે."""
    return ", ".join(_WORDS[int(c)] if c.isdigit() else _LETTERS.get(c, c) for c in code.upper())


def _code_symbol(token: str) -> str | None:
    if (letter := _LETTER_OF.get(token)) is not None:
        return letter
    if (value := _VALUE.get(token)) is not None and value < 10:
        return str(value)
    return token.upper() if re.fullmatch(r"[A-Za-z0-9]", token) else None


def code_from_speech(text: str) -> str:
    """The reverse of spell_code: "કે, સાત, ક્યૂ, બે" -> "K 7 Q 2", leaving other text alone.

    A code is read with a comma after every symbol, and that's what tells it from ordinary speech:
    "કે" and "એ" are everyday words, so "સાત, આઠ કે નવ વાગ્યે" (seven, eight or nine o'clock) holds
    four symbols in a row but is no code. Only a word that stands alone between commas joins a run;
    a longer piece can end a run with its first word and start one with its last.
    """
    best: list[str] = []
    run: list[str] = []
    for piece in to_ascii_digits(text).split(","):
        tokens = _TOKEN.findall(piece)
        if not tokens:
            best, run = max(best, run, key=len), []
            continue
        first = _code_symbol(tokens[0])
        if len(tokens) == 1 and first:
            run.append(first)
            continue
        if first and run:
            run.append(first)
        best = max(best, run, key=len)
        last = _code_symbol(tokens[-1])
        run = [last] if last else []
    best = max(best, run, key=len)
    return " ".join(best) if len(best) >= 4 and any(s.isalpha() for s in best) else text
