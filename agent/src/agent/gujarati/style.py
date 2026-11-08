"""What makes a Gujarati reply sound written, not spoken: a linter for agent lines.

Checks wording only. It can catch bookish words and a wrong pronoun; it can't hear whether a line
sounds natural. That takes a native speaker. tests/test_script.py runs every fixed line of the survey
through it, so a stiff or wrongly gendered line fails CI before anyone hears it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent.gujarati.understanding import words

MAX_WORDS = 25

# Written Gujarati a person wouldn't say on the phone, with what they'd say instead.
BOOKISH = {
    "એકત્રિત": "ભેગું",
    "સંપર્ક": "ફોન",
    "ઉપલબ્ધ": "મળશે / છે",
    "આવશ્યકતા": "જરૂર",
    "આવશ્યક": "જરૂરી",
    "વિનંતી": "જરા ... કહેશો?",
    "કૃપા": "જરા",
    "ક્ષમા": "માફ કરજો",
    "પ્રદાન": "આપવું",
    "આપનું": "તમારું",
    "આપની": "તમારી",
    "આપનો": "તમારો",
    "આપના": "તમારા",
    "સેવામાં": "(drop it)",
    "ઉલ્લેખ": "કહેવું",
    "જણાવશો": "કહેશો",
    "જણાવવા": "કહેવા",
    "પ્રક્રિયા": "(say what happens)",
    "પુષ્ટિ": "કન્ફર્મ",
    "આરક્ષણ": "બુકિંગ",
    "રદ્દ": "કેન્સલ",
    "કિંમત": "ભાવ",
}
# A passive that sounds like a government notice: "કરવામાં આવશે".
_PASSIVE = re.compile(r"કરવામાં\s*આવ(?:શે|ે\s*છે|ી\s*છે|્યું|્યો)")
_INTIMATE = {"તું", "તને", "તારું", "તારો", "તારી", "તારા", "તારે"}
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
_ALLOWED_LATIN = {"AI"}
_FEMININE_SELF = ("સમજી ગઈ", "રહી છું", "ગઈ છું")
_MASCULINE_SELF = ("સમજી ગયો", "રહ્યો છું", "ગયો છું")


@dataclass(frozen=True)
class Problem:
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.rule}: {self.detail}"


def check_line(line: str, gender: str = "male") -> list[Problem]:
    """What's wrong with one agent line; an empty list if nothing is."""
    tokens = words(line)
    problems = []
    if len(tokens) > MAX_WORDS:
        problems.append(Problem("too_long", f"{len(tokens)} words"))
    # "કેમ છો?" is a greeting, so it doesn't count as asking something.
    if line.replace("કેમ છો?", "").count("?") > 1:
        problems.append(Problem("two_questions", line))
    for token in tokens:
        for word, better in BOOKISH.items():
            if token.startswith(word):
                problems.append(Problem("bookish", f"{token} -> {better}"))
        if token in _INTIMATE:
            problems.append(Problem("intimate_pronoun", token))
    if _PASSIVE.search(line):
        problems.append(Problem("passive", "કરવામાં આવશે"))
    for latin in _LATIN_WORD.findall(line):
        if latin not in _ALLOWED_LATIN:
            problems.append(Problem("latin_script", latin))
    for form in _FEMININE_SELF if gender == "male" else _MASCULINE_SELF:
        if form in line:
            problems.append(Problem("wrong_gender", form))
    return problems


_OPENERS = ("હા, બિલકુલ", "સરસ", "બરાબર", "સારું", "એક મિનિટ", "કોઈ વાંધો નહીં", "હા")


def opener(line: str) -> str | None:
    """The acknowledgement a line starts with, if any."""
    return next((o for o in _OPENERS if line.startswith(o)), None)


def repeated_openers(agent_lines: list[str]) -> int:
    """How many times a reply opens with the same acknowledgement as the reply before it."""
    said = [opener(line) for line in agent_lines]
    return sum(1 for a, b in zip(said, said[1:], strict=False) if a and a == b)
