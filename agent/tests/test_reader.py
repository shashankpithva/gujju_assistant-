"""Reading a turn: the rules for plain answers, the LLM for the rest, the rules again if it fails."""

import asyncio

import pytest

from agent.places import gujarat
from agent.survey.flow import Reading, Survey
from agent.survey.reader import (
    AnswerReader,
    asked_just_now,
    describe_turn,
    fallback_reading,
    read_back_just_now,
    reading_from,
)
from agent.survey.script import CHECK_IN, QUESTIONS
from tests.conftest import ScriptedLLM


def at(field: str) -> Survey:
    survey = Survey()
    survey.opening()
    survey.asked = field
    return survey


async def test_names_and_places_go_to_the_llm_with_the_question_and_the_words():
    model = ScriptedLLM({"મારું નામ રમેશભાઈ પટેલ": {"intent": "answer", "name": "રમેશભાઈ પટેલ"}})
    reading = await AnswerReader(model).read(at("name"), "મારું નામ રમેશભાઈ પટેલ", last_line="તમારું નામ શું છે?")
    assert reading == Reading("answer", {"name": "રમેશભાઈ પટેલ"}, source="llm")
    assert model.tool_choices == ["required"]  # it must answer with the function, never in words
    prompt = model.requests[0].items[-1].text_content
    assert 'Question just asked: name ("તમારું નામ શું છે?")' in prompt


async def test_a_plain_yes_or_number_skips_the_llm():
    model = ScriptedLLM()
    survey = at("water_supply")
    reading = await AnswerReader(model).read(survey, "હા, આવે છે", last_line=QUESTIONS["water_supply"].ask)
    assert reading == Reading("answer", {"water_supply": True}, source="rules")
    survey.asked = "duration"
    reading = await AnswerReader(model).read(survey, "અડધો કલાક", last_line=QUESTIONS["duration"].ask)
    assert reading.values == {"duration_minutes": 30}
    assert model.requests == []


async def test_yes_to_can_you_hear_me_is_not_yes_to_the_question():
    # After the silence check-in, "હા" means "I can hear you", not "water comes".
    model = ScriptedLLM({"હા": {"intent": "acknowledge"}})
    reading = await AnswerReader(model).read(at("water_supply"), "હા", last_line=CHECK_IN)
    assert reading.intent == "acknowledge" and len(model.requests) == 1
    assert fallback_reading("water_supply", "હા", asked=False).intent == "acknowledge"
    assert not asked_just_now("water_supply", CHECK_IN)
    assert asked_just_now("water_supply", f"સારું. {QUESTIONS['water_supply'].ask}")
    assert asked_just_now("water_supply", QUESTIONS["water_supply"].again)


async def test_when_the_llm_fails_the_rules_keep_the_call_going():
    reader = AnswerReader(ScriptedLLM(fail=True))
    assert (await reader.read(at("village"), "અમારું ગામ ખાંભા છે")).values == {"village": "ખાંભા"}
    assert (await reader.read(at("name"), "હું બિઝી છું, પછી ફોન કરજો")).intent == "busy"
    assert (await reader.read(at("frequency"), "રોજ સવારે આવે")).values == {"frequency_days": 1.0}


async def test_a_slow_llm_is_given_up_on():
    model = ScriptedLLM({"ખાંભા": {"intent": "answer", "village": "ખાંભા"}})
    model.delay = 1.0
    reading = await AnswerReader(model, timeout=0.05).read(at("village"), "ખાંભા")
    assert reading.source == "fallback" and reading.values == {"village": "ખાંભા"}


async def test_without_an_llm_the_rules_read_everything():
    reading = await AnswerReader(None).read(at("name"), "રમેશ")
    assert reading == Reading("answer", {"name": "રમેશ"}, source="fallback")


def test_what_the_llm_records_is_checked():
    reading = reading_from(
        {
            "intent": "answer",
            "name": "  રમેશ ",
            "village": "unknown",  # a stand-in, not a place
            "district": "",
            "water_supply": "maybe",
            "frequency_days": "2",
            "duration_minutes": 5000,  # longer than a day
            "duration_note": "નક્કી નહીં",
        }
    )
    assert reading.values == {"name": "રમેશ", "frequency_days": 2.0, "duration_note": "નક્કી નહીં"}


def test_an_answer_with_nothing_in_it_is_unclear():
    assert reading_from({"intent": "answer", "name": "null"}).intent == "unclear"
    assert reading_from({"intent": "nonsense"}).intent == "unclear"
    assert reading_from({}).intent == "unclear"


def test_a_question_always_says_what_about():
    assert reading_from({"intent": "question"}).asked_about == "other"
    assert reading_from({"intent": "question", "asked_about": "who"}).asked_about == "who"
    assert reading_from({"intent": "answer", "name": "x", "asked_about": "who"}).asked_about is None


def test_water_supply_may_come_as_a_boolean():
    assert reading_from({"intent": "answer", "water_supply": False}).values == {"water_supply": False}


@pytest.mark.parametrize(
    ("field", "said", "intent", "values"),
    [
        ("name", "", "unclear", {}),
        ("name", "આવજો", "goodbye", {}),
        ("name", "શું?", "repeat", {}),
        ("name", "હા બોલો", "unclear", {}),
        ("name", "અમારા ગામમાં તો પાણી બહુ ઓછું આવે છે ભાઈ", "unclear", {}),  # a sentence, not a name
        ("taluka", "ખાંભા તાલુકો", "answer", {"taluka": "ખાંભા"}),
        ("water_supply", "નથી આવતું", "answer", {"water_supply": False}),
        ("duration", "સવા કલાક", "answer", {"duration_minutes": 75}),
        ("duration", "ખબર નથી", "unclear", {}),
    ],
)
def test_the_fallback_rules(field, said, intent, values):
    reading = fallback_reading(field, said)
    assert (reading.intent, reading.values) == (intent, values)


def test_the_llm_sees_what_has_been_answered():
    survey = Survey()
    survey.opening()
    survey.respond(Reading("answer", {"name": "રમેશ"}))
    text = describe_turn(survey, "ખાંભા  ગામ", f"આભાર, રમેશ. {QUESTIONS['village'].ask}")
    assert "Answers so far: name: રમેશ" in text
    assert 'What the person said: "ખાંભા ગામ"' in text
    assert "The agent's last words: \"આભાર, રમેશ." in text


async def test_reading_takes_no_longer_than_its_timeout():
    model = ScriptedLLM()
    model.delay = 5
    started = asyncio.get_running_loop().time()
    await AnswerReader(model, timeout=0.1).read(at("name"), "રમેશ")
    assert asyncio.get_running_loop().time() - started < 1


# A place read back for a yes ---------------------------------------------------------------------


def read_back(village: str = "ખાંભા") -> Survey:
    """A survey that has just asked "તમારું ગામ ખાંભા, બરાબર?"."""
    survey = Survey(places=gujarat())
    survey.opening()
    survey.respond(Reading("answer", {"name": "રમેશ"}))
    survey.respond(Reading("answer", {"village": village}))
    assert survey.confirming
    return survey


@pytest.mark.parametrize(
    ("said", "yes"), [("હા", True), ("હા, બરાબર", True), ("ના", False), ("ના જી, ખોટું", False)]
)
async def test_a_plain_yes_or_no_to_a_place_skips_the_llm(said, yes):
    model = ScriptedLLM()
    survey = read_back()
    reading = await AnswerReader(model).read(survey, said, last_line=survey.confirmation)
    assert reading == Reading("answer", source="rules", confirm=yes)
    assert model.requests == []


async def test_a_no_with_a_name_goes_to_the_llm():
    model = ScriptedLLM(
        {"ના, ધારી": {"intent": "answer", "confirm": "no", "village": "ધારી", "village_en": "Dhari"}}
    )
    survey = read_back()
    reading = await AnswerReader(model).read(survey, "ના, ધારી", last_line=survey.confirmation)
    assert reading.confirm is False and reading.values == {"village": "ધારી", "village_en": "Dhari"}
    prompt = model.requests[0].items[-1].text_content
    assert 'Read back for a yes or no: village ખાંભા ("તમારું ગામ ખાંભા, બરાબર?")' in prompt


async def test_yes_to_can_you_hear_me_is_not_yes_to_the_place():
    # After the silence check-in, "હા" means "I can hear you", not "Khambha is right".
    model = ScriptedLLM({"હા": {"intent": "acknowledge", "confirm": "yes"}})  # even if the LLM thinks so
    survey = read_back()
    reading = await AnswerReader(model).read(survey, "હા", last_line=CHECK_IN)
    assert reading.confirm is None and len(model.requests) == 1
    assert not read_back_just_now(survey, CHECK_IN) and read_back_just_now(survey, survey.confirmation)
    assert "Read back for a yes or no" not in model.requests[0].items[-1].text_content


async def test_without_the_llm_a_place_is_still_confirmed():
    reader = AnswerReader(ScriptedLLM(fail=True))
    survey = read_back()
    no = await reader.read(survey, "ના ના, ધારી", last_line=survey.confirmation)
    assert (no.confirm, no.values) == (False, {"village": "ધારી"})
    again = await reader.read(survey, "ખાંભા", last_line=survey.confirmation)  # the name again: a yes
    assert (again.confirm, again.values) == (None, {"village": "ખાંભા"})
    assert (await reader.read(survey, "અમમ", last_line=survey.confirmation)).values == {"village": "અમમ"}
    assert fallback_reading("village", "", confirming="village").intent == "unclear"


def test_the_llm_may_give_a_yes_a_no_and_english_spellings():
    reading = reading_from({"intent": "answer", "confirm": "yes"})
    assert reading.intent == "answer" and reading.confirm is True and reading.values == {}
    reading = reading_from({"intent": "answer", "taluka": "ધારી", "taluka_en": " Dhari ", "confirm": "maybe"})
    assert reading.values == {"taluka": "ધારી", "taluka_en": "Dhari"} and reading.confirm is None
