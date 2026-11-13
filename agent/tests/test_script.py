"""Every fixed line passes the Gujarati style rules, and the call says plainly that it's an AI."""

import pytest

from agent.gujarati.style import check_line
from agent.survey import script
from agent.survey.script import QUESTIONS, Script, with_suffix

CONSTANT_LINES = [
    value
    for name, value in vars(script).items()
    if name.isupper() and isinstance(value, str) and any("઀" <= ch <= "૿" for ch in value)
]
QUESTION_LINES = [line for q in QUESTIONS.values() for line in (q.ask, q.again, q.unlisted) if line]
# Lines built around a place's name.
PLACE_LINES = [
    *(line.format("ખાંભા") for line in script.CONFIRM_PLACE.values()),
    script.CONFIRM_SEVERAL.format(
        ", ".join(phrase.format("ખાંભા") for phrase in script.PLACE_PHRASES.values())
    ),
    *(f"{ack} {QUESTIONS['taluka'].ask}" for ack in script.CONFIRMED.values()),
]
SCRIPTS = [Script(), Script(org="ગ્રામ પંચાયત"), Script(org="જળ સેવા ટ્રસ્ટ")]
SCRIPT_LINES = [line for s in SCRIPTS for line in (s.intro(), s.who(), s.why())]


@pytest.mark.parametrize("line", CONSTANT_LINES + QUESTION_LINES + SCRIPT_LINES + PLACE_LINES)
@pytest.mark.parametrize("gender", ["male", "female"])
def test_every_line_sounds_spoken_and_fits_either_voice(line, gender):
    # Bookish words, તું, passives, two questions in one line, stray English, and verbs that would
    # give the speaker a gender: the same text is said by any voice.
    assert check_line(line, gender) == []


def test_each_question_is_one_question():
    for question in QUESTIONS.values():
        assert question.ask.endswith("?") and question.again.endswith("?")
        assert question.ask != question.again


def test_every_place_question_says_when_a_name_isnt_in_the_list():
    for field in script.PLACE_FIELDS:
        assert QUESTIONS[field].unlisted.endswith("?") and "યાદી" in QUESTIONS[field].unlisted
    assert all(line.endswith("બરાબર?") for line in script.CONFIRM_PLACE.values())


def test_the_introduction_says_who_it_is_and_that_its_an_ai():
    for s in SCRIPTS:
        assert "AI" in s.intro() and s.org in s.intro()
        assert "AI" in s.who()
    assert "માણસ" not in Script().who()  # never claims to be a person, in either direction


def test_org_names_take_their_postposition_the_right_way():
    assert with_suffix("ગ્રામ પંચાયત", "નો") == "ગ્રામ પંચાયતનો"
    assert with_suffix("Jal Seva", "નો") == "Jal Seva નો"


def test_the_script_reads_its_settings(monkeypatch):
    monkeypatch.setenv("SURVEY_ORG_NAME", "  ગ્રામ   પંચાયત ")
    monkeypatch.setenv("SURVEY_PURPOSE", "")
    s = Script.from_env()
    assert s.org == "ગ્રામ પંચાયત" and s.purpose == script.DEFAULT_PURPOSE
