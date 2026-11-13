"""An English place name in Gujarati letters, so the Gujarati voice says it the Gujarati way.

Only for reading a village back when it has no Gujarati name in the list and the person's own words
didn't match it exactly (gazetteer.Match.spoken). English spellings don't say whether "t" is ત or ટ,
or "a" is અ or આ, so this spells how the name sounds, not how it's written in Gujarati: right for the
ear, not for the sheet, which keeps the official English name.
"""

from __future__ import annotations

import re

# Longest spelling first.
_CONSONANTS = (
    ("chh", "છ"), ("ksh", "ક્ષ"), ("kh", "ખ"), ("gh", "ઘ"), ("ch", "ચ"), ("jh", "ઝ"), ("th", "થ"),
    ("dh", "ધ"), ("ph", "ફ"), ("bh", "ભ"), ("sh", "શ"), ("k", "ક"), ("c", "ક"), ("q", "ક"), ("g", "ગ"),
    ("j", "જ"), ("z", "ઝ"), ("t", "ત"), ("d", "દ"), ("n", "ન"), ("p", "પ"), ("f", "ફ"), ("b", "બ"),
    ("m", "મ"), ("y", "ય"), ("r", "ર"), ("l", "લ"), ("v", "વ"), ("w", "વ"), ("s", "સ"), ("h", "હ"),
    ("x", "ક્સ"),
)  # fmt: skip
# (spelling, the vowel on its own, the vowel after a consonant)
_VOWELS = (
    ("aa", "આ", "ા"), ("ai", "ઐ", "ૈ"), ("au", "ઔ", "ૌ"), ("ee", "ઈ", "ી"), ("oo", "ઊ", "ૂ"),
    ("a", "અ", ""), ("i", "ઇ", "િ"), ("u", "ઉ", "ુ"), ("e", "એ", "ે"), ("o", "ઓ", "ો"),
)  # fmt: skip
# At the end of a word, English writes "a", "i" for what Gujarati says long: "Khambha", "Amreli".
_FINAL = {"a": "ા", "i": "ી"}
_VIRAMA, _ANUSVARA = "્", "ં"
_GLIDE_AFTER = {"i", "ee", "e", "ai"}  # "Pipalia": પિપલિયા, with a ય between the two vowels
# Before these, "n" or "m" is a nasal on the vowel ("Khambha": ખંભા); before r, l, v, y, s or h it's a
# letter of its own ("Amreli": અમ્રેલી).
_STOPS = {
    "k",
    "kh",
    "c",
    "q",
    "g",
    "gh",
    "ch",
    "chh",
    "j",
    "jh",
    "z",
    "t",
    "th",
    "d",
    "dh",
    "p",
    "ph",
    "f",
    "b",
    "bh",
}


def _units(word: str) -> list[tuple[str, str]]:
    """("c", "kh") and ("v", "a") pieces of a lowercase word, longest spelling first."""
    units: list[tuple[str, str]] = []
    i = 0
    while i < len(word):
        for spelling, *_ in _VOWELS:
            if word.startswith(spelling, i):
                units.append(("v", spelling))
                i += len(spelling)
                break
        else:
            for spelling, _ in _CONSONANTS:
                if word.startswith(spelling, i):
                    units.append(("c", spelling))
                    i += len(spelling)
                    break
            else:
                i += 1  # not a letter of a name
    return units


def _word(word: str) -> str:
    units = _units(word)
    consonants = dict(_CONSONANTS)
    vowels = {spelling: (alone, sign) for spelling, alone, sign in _VOWELS}
    out: list[str] = []
    for i, (kind, spelling) in enumerate(units):
        before = units[i - 1] if i else None
        after = units[i + 1] if i + 1 < len(units) else None
        last = after is None
        if kind == "v":
            if before is not None and before[0] == "c":
                out.append(_FINAL.get(spelling, vowels[spelling][1]) if last else vowels[spelling][1])
            elif before is not None and before[1] in _GLIDE_AFTER:
                out.append("ય" + (_FINAL.get(spelling, vowels[spelling][1]) if last else vowels[spelling][1]))
            else:
                out.append(vowels[spelling][0])
            continue
        nasal = spelling in ("n", "m") and before is not None and before[0] == "v"
        if nasal and after is not None and after[1] in _STOPS:
            out.append(_ANUSVARA)
            continue
        out.append(consonants[spelling])
        if after is not None and after[0] == "c":
            out.append(_VIRAMA)
    return "".join(out)


def to_gujarati(name: str) -> str:
    """ "Dholarva" -> "ધોલર્વા", "Pipalia" -> "પિપલિયા": approximately, for the voice to read."""
    return " ".join(_word(w) for w in re.split(r"[^a-z]+", name.lower()) if w)
