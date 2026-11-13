"""A place name as it sounds, whether written in Gujarati or in English letters.

The official list is in English ("Khambha", "Deodar"); speech-to-text writes what people say in
Gujarati ("ખાંભા", "દિયોદર"), with spellings that vary ("ખંભા", "ખાભા"). Comparing the letters
would fail, so both are turned into a key that keeps how a name sounds and drops what spellings
disagree on:
- vowel length (આ/અ, ઈ/ઇ, ઊ/ઉ, "ee"/"i") and e/i, o/u, which English spellings mix up;
- aspiration (ખ/ક, ભ/બ, "kh"/"k") and dental/retroflex (ત/ટ, દ/ડ, ન/ણ);
- ચ/છ, શ/ષ/સ, વ/"w", ઝ/"z"/"j", ય as a glide ("Diyodar", "Deodar");
- the short "a" Gujarati writes but doesn't say ("અમરેલી" is "amreli", not "amareli").

Whether a short "a" inside a word is said depends on the word: "અમરેલી" is "amreli", "ઢોલરવા" is
"dholarva", but "ગાંધીનગર" keeps its "a" ("gandhinagar": Gandhi + nagar). No one rule gets them all,
so Gujarati gets a key for each rule (`keys`), and the closest one counts.

`skeleton` goes further and keeps only the consonants, for names whose vowels differ more.
"""

from __future__ import annotations

import re

_CONSONANTS = {
    "ક": "k", "ખ": "kh", "ગ": "g", "ઘ": "gh", "ઙ": "n", "ચ": "ch", "છ": "chh", "જ": "j", "ઝ": "jh",
    "ઞ": "n", "ટ": "t", "ઠ": "th", "ડ": "d", "ઢ": "dh", "ણ": "n", "ત": "t", "થ": "th", "દ": "d",
    "ધ": "dh", "ન": "n", "પ": "p", "ફ": "ph", "બ": "b", "ભ": "bh", "મ": "m", "ય": "y", "ર": "r",
    "લ": "l", "ળ": "l", "વ": "v", "શ": "sh", "ષ": "sh", "સ": "s", "હ": "h",
}  # fmt: skip
_VOWELS = {
    "અ": "a", "આ": "a", "ઇ": "i", "ઈ": "i", "ઉ": "u", "ઊ": "u", "ઋ": "ru", "ૠ": "ru", "ઌ": "lu",
    "એ": "e", "ઐ": "ai", "ઓ": "o", "ઔ": "au", "ઍ": "e", "ઑ": "o",
}  # fmt: skip
_SIGNS = {
    "ા": "a", "િ": "i", "ી": "i", "ુ": "u", "ૂ": "u", "ૃ": "ru", "ૄ": "ru", "ે": "e", "ૈ": "ai",
    "ો": "o", "ૌ": "au", "ૅ": "e", "ૉ": "o",
}  # fmt: skip
_VIRAMA, _ANUSVARA, _CANDRABINDU, _VISARGA, _NUKTA = "્", "ં", "ઁ", "ઃ", "઼"
_SCHWA = "@"  # the short "a" every Gujarati consonant carries until a sign or virama says otherwise
_NASAL = "N"  # anusvara: "m" before p, b or m, "n" elsewhere, as English spells it
_LABIALS = "pbm"
_VOWEL_LETTERS = set("aeiou@")

# English spellings, longest first, as one sound each.
_SPELLINGS = [
    ("chh", "c"), ("ch", "c"), ("sh", "s"), ("kh", "k"), ("gh", "g"), ("jh", "j"), ("th", "t"),
    ("dh", "d"), ("bh", "b"), ("ph", "f"), ("ee", "i"), ("oo", "u"), ("aa", "a"), ("z", "j"),
    ("w", "v"), ("q", "k"), ("x", "ks"),
]  # fmt: skip
_BRACKETS = re.compile(r"\([^)]*\)")
_NOT_LETTERS = re.compile(r"[^a-z]+")
_REPEATS = re.compile(r"(.)\1+")


def romanize(text: str, *, schwa: str = "left") -> str:
    """Gujarati letters in plain lowercase Latin, as a name is said: "અમરેલી" -> "amreli".
    Latin letters pass through, lowercased; anything else becomes a space. `schwa` is how the short
    "a" inside a word is dropped (see `_finish_word`)."""
    out: list[str] = []
    chars = list(text)
    for i, ch in enumerate(chars):
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        if ch in _CONSONANTS:
            out.append(_CONSONANTS[ch])
            after = chars[i + 2] if nxt == _NUKTA and i + 2 < len(chars) else nxt
            if after not in _SIGNS and after != _VIRAMA:
                out.append(_SCHWA)
        elif ch in _VOWELS:
            out.append(_VOWELS[ch])
        elif ch in _SIGNS:
            out.append(_SIGNS[ch])
        elif ch == _ANUSVARA:
            out.append(_NASAL)
        elif ch == _VISARGA:
            out.append("h")
        elif ch in (_VIRAMA, _NUKTA, _CANDRABINDU):
            continue
        elif ch.isascii() and ch.isalpha():
            out.append(ch.lower())
        else:
            out.append(" ")
    return " ".join(_finish_word(word, schwa) for word in "".join(out).split())


SCHWA_RULES = ("left", "right", "keep")


def _finish_word(word: str, schwa: str) -> str:
    """Drop the short "a" Gujarati doesn't say: always at the end of a word, and inside it between a
    vowel+consonant and a consonant+vowel, scanning from the `left` ("ભાવનગર" is "bhavnagar") or the
    `right` ("ઢોલરવા" is "dholarva"), or not at all (`keep`: "ગાંધીનગર" is "gandhinagar").
    Then resolve each anusvara to "m" or "n"."""
    letters = list(word)
    if letters and letters[-1] == _SCHWA:
        letters.pop()

    def silent(i: int) -> bool:
        return (
            2 <= i < len(letters) - 2
            and letters[i] == _SCHWA
            and letters[i - 1] not in _VOWEL_LETTERS
            and letters[i - 2] in _VOWEL_LETTERS
            and letters[i + 1] not in _VOWEL_LETTERS
            and letters[i + 2] in _VOWEL_LETTERS
        )

    if schwa == "left":
        i = 2
        while i < len(letters) - 2:
            if silent(i):
                del letters[i]
            i += 1
    elif schwa == "right":
        for i in range(len(letters) - 3, 1, -1):
            if silent(i):
                del letters[i]
    text = "".join(letters).replace(_SCHWA, "a")
    return re.sub(
        _NASAL + r"(?=([a-z]?))", lambda m: "m" if m.group(1) in _LABIALS and m.group(1) else "n", text
    )


def keys(text: str) -> set[str]:
    """Every key a name may have: one for English letters, one per schwa rule for Gujarati (see the
    module notes)."""
    rules = SCHWA_RULES if is_gujarati(text) else ("left",)
    found = {key(text, schwa=rule) for rule in rules}
    found.discard("")
    return found


def is_gujarati(text: str) -> bool:
    return any("\u0a80" <= ch <= "\u0aff" for ch in text)


def key(text: str, *, schwa: str = "left") -> str:
    """How a name sounds, in a form that a Gujarati and an English spelling of it share."""
    text = _BRACKETS.sub(" ", text)
    words = romanize(text, schwa=schwa).split()
    joined = []
    for word in words:
        for spelling, sound in _SPELLINGS:
            word = word.replace(spelling, sound)
        word = word.replace("e", "i").replace("o", "u")
        word = word[:1] + word[1:].replace("y", "")  # a glide, written by some and not by others
        joined.append(word)
    return _REPEATS.sub(r"\1", _NOT_LETTERS.sub("", "".join(joined)))


def skeleton(text_key: str) -> str:
    """Only the consonants of a key (and its first letter): what's left when vowels disagree."""
    return text_key[:1] + "".join(c for c in text_key[1:] if c not in "aeiou")
