"""The survey's path through a call: one reading in, one line out."""

import pytest

from agent.survey.answers import NOT_APPLICABLE, UNCLEAR
from agent.survey.flow import MAX_TURNS, Reading, Survey
from agent.survey.script import (
    BUSY,
    CHECK_IN,
    DECLINED,
    DONT_KNOW,
    EARLY_GOODBYE,
    FIELDS,
    MOVE_ON,
    NO_WATER,
    ONCE_MORE,
    QUESTIONS,
    RECORDED,
    TO_WATER,
    WAITING,
    Script,
)


def answer(**values) -> Reading:
    return Reading("answer", values)


@pytest.fixture
def survey() -> Survey:
    s = Survey()
    s.opening()
    return s


def answer_all(survey: Survey, *, water: bool = True) -> list[str]:
    lines = [
        survey.respond(answer(name="રમેશભાઈ પટેલ")).line,
        survey.respond(answer(village="ખાંભા")).line,
        survey.respond(answer(taluka="ખાંભા")).line,
        survey.respond(answer(district="અમરેલી")).line,
        survey.respond(answer(water_supply=water)).line,
    ]
    if water:
        lines.append(survey.respond(answer(frequency_days=2.0)).line)
        lines.append(survey.respond(answer(duration_minutes=60)).line)
    return lines


def test_the_call_opens_with_who_it_is_that_its_an_ai_and_the_first_question():
    survey = Survey(Script(org="ગ્રામ પંચાયત"))
    intro, question = survey.opening()
    assert "ગ્રામ પંચાયત" in intro and "AI" in intro and "સર્વે" in intro
    assert question == QUESTIONS["name"].ask
    assert survey.asked == "name"


def test_the_seven_questions_come_in_order_and_each_answer_is_said_back(survey):
    lines = answer_all(survey)
    assert lines[0] == f"આભાર, રમેશભાઈ પટેલ. {QUESTIONS['village'].ask}"
    assert lines[1] == f"સરસ, ખાંભા. {QUESTIONS['taluka'].ask}"
    assert lines[2] == f"ખાંભા તાલુકો, બરાબર. {QUESTIONS['district'].ask}"
    assert lines[3] == f"અમરેલી જિલ્લો. {TO_WATER} {QUESTIONS['water_supply'].ask}"
    assert lines[4] == f"સારું. {QUESTIONS['frequency'].ask}"
    assert lines[5] == f"એકાંતરે, ઠીક છે. {QUESTIONS['duration'].ask}"
    assert lines[6].startswith("1 કલાક, બરાબર.") and RECORDED in lines[6] and lines[6].endswith("આવજો!")
    assert survey.status == "completed"


def test_the_last_answer_ends_the_call(survey):
    answer_all(survey)
    assert survey.finished
    assert survey.respond(answer(name="x")).end  # nothing more is asked


def test_the_sheet_gets_every_answer_written_out(survey):
    answer_all(survey)
    assert survey.sheet_values() == {
        "name": "રમેશભાઈ પટેલ",
        "village": "ખાંભા",
        "taluka": "ખાંભા",
        "district": "અમરેલી",
        "water_supply": "હા",
        "frequency": "એકાંતરે (દર 2 દિવસે)",
        "duration": "1 કલાક (60 મિનિટ)",
    }


def test_no_water_skips_how_often_and_how_long(survey):
    lines = answer_all(survey, water=False)
    assert lines[-1].startswith(NO_WATER) and RECORDED in lines[-1]
    assert survey.status == "completed"
    values = survey.sheet_values()
    assert values["water_supply"] == "ના"
    assert values["frequency"] == values["duration"] == NOT_APPLICABLE


def test_several_answers_at_once_are_all_taken(survey):
    survey.respond(answer(name="સીતા"))
    reply = survey.respond(answer(village="ધોળકા", taluka="ધોળકા", district="અમદાવાદ"))
    assert reply.line == (
        f"બરાબર, ધોળકા ગામ, ધોળકા તાલુકો અને અમદાવાદ જિલ્લો. {TO_WATER} {QUESTIONS['water_supply'].ask}"
    )
    assert reply.changed == ("village", "taluka", "district")


def test_how_often_said_with_yes_answers_both(survey):
    for reading in (answer(name="a"), answer(village="b"), answer(taluka="c"), answer(district="d")):
        survey.respond(reading)
    reply = survey.respond(answer(water_supply=True, frequency_days=1.0))
    assert reply.line == f"બરાબર, પાણી આવે છે અને રોજ. {QUESTIONS['duration'].ask}"


def test_how_often_alone_means_water_comes(survey):
    for reading in (answer(name="a"), answer(village="b"), answer(taluka="c"), answer(district="d")):
        survey.respond(reading)
    survey.respond(answer(frequency_days=2.0))  # "એકાંતરે આવે છે" to "does water come?"
    assert survey.answers.water_supply is True
    assert survey.asked == "duration"


def test_a_correction_to_an_earlier_answer_is_taken_and_the_question_stands(survey):
    survey.respond(answer(name="રમેશ"))
    survey.respond(answer(village="ખાંભા"))
    reply = survey.respond(answer(village="ખંભાળિયા"))  # asked the taluka: "no, the village is..."
    assert reply.line == f"બરાબર, ખંભાળિયા ગામ. {QUESTIONS['taluka'].ask}"
    assert survey.answers.village == "ખંભાળિયા" and survey.asked == "taluka"


def test_an_unclear_answer_gets_asked_again_in_other_words_then_the_survey_moves_on(survey):
    first = survey.respond(Reading("unclear")).line
    second = survey.respond(Reading("unclear")).line
    third = survey.respond(Reading("unclear")).line
    assert first == QUESTIONS["name"].again
    assert second == f"{ONCE_MORE} {QUESTIONS['name'].ask}"  # never the same line twice in a row
    assert third == f"{MOVE_ON} {QUESTIONS['village'].ask}"
    assert "name" in survey.skipped and survey.sheet_values()["name"] == UNCLEAR


def test_a_skipped_question_is_filled_in_if_answered_later(survey):
    for _ in range(3):
        survey.respond(Reading("unclear"))
    survey.respond(answer(name="રમેશ", village="ખાંભા"))
    assert "name" not in survey.skipped and survey.answers.name == "રમેશ"


def test_repeat_and_acknowledge_ask_the_same_question_plainly(survey):
    assert survey.respond(Reading("repeat")).line == QUESTIONS["name"].ask
    assert survey.respond(Reading("acknowledge")).line == QUESTIONS["name"].ask


def test_questions_back_are_answered_then_the_question_is_asked_again():
    survey = Survey(Script(org="ગ્રામ પંચાયત"))
    survey.opening()
    who = survey.respond(Reading("question", asked_about="who")).line
    assert who.startswith("હું ગ્રામ પંચાયતનો AI આસિસ્ટન્ટ છું") and who.endswith(QUESTIONS["name"].ask)
    why = survey.respond(Reading("question", asked_about="why")).line
    assert why.startswith(survey.script.purpose)
    other = survey.respond(Reading("question", asked_about="other")).line
    assert other.startswith(DONT_KNOW)


def test_a_question_and_an_answer_in_one_turn_get_both(survey):
    reply = survey.respond(Reading("question", {"name": "રમેશ"}, asked_about="who"))
    assert reply.line.startswith("હું AI આસિસ્ટન્ટ છું")
    assert "આભાર, રમેશ." in reply.line and reply.line.endswith(QUESTIONS["village"].ask)


def test_hold_on_waits_without_asking(survey):
    reply = survey.respond(Reading("wait"))
    assert reply.line == WAITING and not reply.end and survey.asked == "name"


@pytest.mark.parametrize(
    ("intent", "line", "status"), [("busy", BUSY, "busy"), ("refuse", DECLINED, "declined")]
)
def test_busy_or_not_interested_ends_the_call_politely(survey, intent, line, status):
    reply = survey.respond(Reading(intent))
    assert reply.end and reply.line == line and survey.status == status


def test_a_goodbye_partway_keeps_what_was_answered(survey):
    survey.respond(answer(name="રમેશ"))
    reply = survey.respond(Reading("goodbye"))
    assert reply.end and reply.line == EARLY_GOODBYE
    assert survey.status == "partial" and survey.note() == "Call ended at the village question"


def test_a_call_cut_short_is_partial_or_no_answer():
    silent = Survey()
    silent.opening()
    assert silent.end() == "no_answer" and silent.note() == "Picked up, but didn't answer"
    talked = Survey()
    talked.opening()
    talked.respond(Reading("unclear"))
    assert talked.end() == "partial"


def test_the_turn_cap_stops_a_call_going_round_in_circles(survey):
    lines = [survey.respond(Reading("acknowledge")).line for _ in range(MAX_TURNS)]
    assert lines[-1] == f"{MOVE_ON} {QUESTIONS['village'].ask}"


def test_lost_words_are_asked_again_without_counting_against_the_person(survey):
    assert survey.didnt_hear() == QUESTIONS["name"].again
    assert survey.didnt_hear() == f"{ONCE_MORE} {QUESTIONS['name'].ask}"
    survey.respond(Reading("unclear"))  # still two tries left: lost words weren't counted
    assert survey.asked == "name"


def test_the_check_in_is_a_question_of_its_own(survey):
    assert survey.check_in() == CHECK_IN


def test_unclear_answers_are_noted_on_a_completed_call(survey):
    for _ in range(3):
        survey.respond(Reading("unclear"))
    for reading in (
        answer(village="b"),
        answer(taluka="c"),
        answer(district="d"),
        answer(water_supply=False),
    ):
        survey.respond(reading)
    assert survey.status == "completed" and survey.note() == "Unclear: name"


def test_every_field_has_a_question():
    assert set(QUESTIONS) == set(FIELDS)
