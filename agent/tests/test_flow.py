"""The survey's path through a call: one reading in, one line out."""

import pytest

from agent.survey.answers import NOT_APPLICABLE, UNCLEAR
from agent.survey.flow import MAX_TURNS, MAX_WRONG_ANSWERS, Reading, Survey, max_wrong_answers
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
    TOO_MANY_WRONG,
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
        survey.respond(answer(age=45)).line,
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


def test_the_eight_questions_come_in_order_and_each_answer_is_said_back(survey):
    lines = answer_all(survey)
    assert lines[0] == f"આભાર, રમેશભાઈ પટેલ. {QUESTIONS['age'].ask}"
    assert lines[1] == f"45 વર્ષ, ઠીક છે. {QUESTIONS['village'].ask}"
    assert lines[2] == f"સરસ, ખાંભા. {QUESTIONS['taluka'].ask}"
    assert lines[3] == f"ખાંભા તાલુકો, બરાબર. {QUESTIONS['district'].ask}"
    assert lines[4] == f"અમરેલી જિલ્લો. {TO_WATER} {QUESTIONS['water_supply'].ask}"
    assert lines[5] == f"સારું. {QUESTIONS['frequency'].ask}"
    assert lines[6] == f"એકાંતરે, ઠીક છે. {QUESTIONS['duration'].ask}"
    assert lines[7].startswith("1 કલાક, બરાબર.") and RECORDED in lines[7] and lines[7].endswith("આવજો!")
    assert survey.status == "completed"


def test_the_last_answer_ends_the_call(survey):
    answer_all(survey)
    assert survey.finished
    assert survey.respond(answer(name="x")).end  # nothing more is asked


def test_the_sheet_gets_every_answer_written_out(survey):
    answer_all(survey)
    assert survey.sheet_values() == {
        "name": "રમેશભાઈ પટેલ",
        "age": "45",
        "village": "ખાંભા",
        "taluka": "ખાંભા",
        "district": "અમરેલી",
        "water_supply": "હા",
        "frequency": "એકાંતરે (દર 2 દિવસે)",
        "duration": "1 કલાક (60 મિનિટ)",
        "days_between": "2",
        "minutes_per_day": "60",
    }


def test_no_water_skips_how_often_and_how_long(survey):
    lines = answer_all(survey, water=False)
    assert lines[-1].startswith(NO_WATER) and RECORDED in lines[-1]
    assert survey.status == "completed"
    values = survey.sheet_values()
    assert values["water_supply"] == "ના"
    assert values["frequency"] == values["duration"] == NOT_APPLICABLE
    assert values["days_between"] == values["minutes_per_day"] == ""


def test_several_answers_at_once_are_all_taken(survey):
    survey.respond(answer(name="સીતા"))
    survey.respond(answer(age=40))
    reply = survey.respond(answer(village="ધોળકા", taluka="ધોળકા", district="અમદાવાદ"))
    assert reply.line == (
        f"બરાબર, ધોળકા ગામ, ધોળકા તાલુકો અને અમદાવાદ જિલ્લો. {TO_WATER} {QUESTIONS['water_supply'].ask}"
    )
    assert reply.changed == ("village", "taluka", "district")


def test_how_often_said_with_yes_answers_both(survey):
    for reading in (answer(name="a", age=30), answer(village="b"), answer(taluka="c"), answer(district="d")):
        survey.respond(reading)
    reply = survey.respond(answer(water_supply=True, frequency_days=1.0))
    assert reply.line == f"બરાબર, પાણી આવે છે અને રોજ. {QUESTIONS['duration'].ask}"


def test_how_often_alone_means_water_comes(survey):
    for reading in (answer(name="a", age=30), answer(village="b"), answer(taluka="c"), answer(district="d")):
        survey.respond(reading)
    survey.respond(answer(frequency_days=2.0))  # "એકાંતરે આવે છે" to "does water come?"
    assert survey.answers.water_supply is True
    assert survey.asked == "duration"


def test_a_correction_to_an_earlier_answer_is_taken_and_the_question_stands(survey):
    survey.respond(answer(name="રમેશ", age=50))
    survey.respond(answer(village="ખાંભા"))
    reply = survey.respond(answer(village="ખંભાળિયા"))  # asked the taluka: "no, the village is..."
    assert reply.line == f"બરાબર, ખંભાળિયા ગામ. {QUESTIONS['taluka'].ask}"
    assert survey.answers.village == "ખંભાળિયા" and survey.asked == "taluka"


def test_unclear_answers_get_the_question_in_other_words_then_the_call_ends_politely(survey):
    survey.respond(answer(name="રમેશ"))
    first = survey.respond(Reading("unclear"))
    second = survey.respond(Reading("unclear"))
    third = survey.respond(Reading("unclear"))
    assert first.line == QUESTIONS["age"].again and not first.end
    assert second.line == f"{ONCE_MORE} {QUESTIONS['age'].ask}"  # never the same line twice in a row
    assert third.end and third.line == TOO_MANY_WRONG
    assert survey.status == "partial"
    assert survey.note() == "Hung up after 3 wrong or unclear answers to the age question"
    values = survey.sheet_values()
    assert values["name"] == "રમેશ" and values["age"] == UNCLEAR and values["village"] == ""


def test_a_skipped_question_is_filled_in_if_answered_later(survey):
    for _ in range(MAX_TURNS):
        survey.respond(Reading("acknowledge"))  # the turn cap leaves the name and asks the age
    assert "name" in survey.skipped and survey.asked == "age"
    survey.respond(answer(name="રમેશ", age=40))
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
    assert "આભાર, રમેશ." in reply.line and reply.line.endswith(QUESTIONS["age"].ask)


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
    assert survey.status == "partial" and survey.note() == "Call ended at the age question"


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
    assert lines[-1] == f"{MOVE_ON} {QUESTIONS['age'].ask}"


def test_lost_words_are_asked_again_without_counting_against_the_person(survey):
    assert survey.didnt_hear() == QUESTIONS["name"].again
    assert survey.didnt_hear() == f"{ONCE_MORE} {QUESTIONS['name'].ask}"
    survey.respond(Reading("unclear"))  # still two tries left: lost words weren't counted
    assert survey.asked == "name"


def test_the_check_in_is_a_question_of_its_own(survey):
    assert survey.check_in() == CHECK_IN


def test_unclear_answers_are_noted_on_a_completed_call(survey):
    for _ in range(MAX_TURNS):
        survey.respond(Reading("acknowledge"))  # the turn cap leaves the name unanswered
    for reading in (
        answer(age=30),
        answer(village="b"),
        answer(taluka="c"),
        answer(district="d"),
        answer(water_supply=False),
    ):
        survey.respond(reading)
    assert survey.status == "completed" and survey.note() == "Unclear: name"


def test_every_field_has_a_question():
    assert set(QUESTIONS) == set(FIELDS)


# Several answers at once, answers to the wrong question, and when the call gives up -----------------


def test_name_and_age_in_one_sentence_skip_the_age_question(survey):
    reply = survey.respond(answer(name="રમેશ પટેલ", age=50))  # "રમેશ પટેલ, ઉંમર પચાસ"
    assert reply.line == f"બરાબર, રમેશ પટેલ અને 50 વર્ષની ઉંમર. {QUESTIONS['village'].ask}"
    assert reply.changed == ("name", "age") and survey.asked == "village"


def test_everything_in_one_sentence_skips_every_question_it_answered(survey):
    reply = survey.respond(answer(name="સીતા", age=60, village="ધોળકા", taluka="ધોળકા", district="અમદાવાદ"))
    assert reply.line.endswith(QUESTIONS["water_supply"].ask) and survey.asked == "water_supply"


def test_an_answer_to_another_question_is_told_what_was_asked_then_the_call_ends(survey):
    survey.respond(answer(name="રમેશ"))
    first = survey.respond(Reading("wrong_answer", {"name": "રમેશ"}))  # their name again, asked the age
    second = survey.respond(Reading("wrong_answer"))
    third = survey.respond(Reading("wrong_answer"))
    assert first.line == QUESTIONS["age"].wrong and not first.end
    assert second.line == f"{ONCE_MORE} {QUESTIONS['age'].ask}" and not second.end
    assert third.end and third.line == TOO_MANY_WRONG and survey.status == "partial"
    assert survey.answers.name == "રમેશ"  # what was answered is kept


def test_wrong_and_unclear_answers_count_together(survey):
    survey.respond(answer(name="રમેશ"))
    assert not survey.respond(Reading("unclear")).end
    assert not survey.respond(Reading("wrong_answer")).end
    assert survey.respond(Reading("unclear")).end


def test_the_count_is_per_question(survey):
    survey.respond(Reading("unclear"))
    survey.respond(Reading("unclear"))
    survey.respond(answer(name="રમેશ"))  # two wrong on the name, then an answer
    survey.respond(Reading("unclear"))
    assert not survey.finished and survey.asked == "age"


def test_a_wrong_answer_never_replaces_an_earlier_answer(survey):
    survey.respond(answer(name="રમેશભાઈ પટેલ"))
    reply = survey.respond(Reading("wrong_answer", {"name": "રમેશ"}))
    assert survey.answers.name == "રમેશભાઈ પટેલ" and reply.changed == ()


def test_the_same_answer_again_is_a_wrong_answer_even_when_read_as_an_answer(survey):
    survey.respond(answer(name="રમેશ"))
    reply = survey.respond(answer(name="રમેશ"))  # the LLM called it an answer, but nothing is new
    assert reply.line == QUESTIONS["age"].wrong


def test_a_correction_while_asked_the_age_is_taken_and_isnt_a_wrong_answer(survey):
    survey.respond(answer(name="મહેશ"))
    reply = survey.respond(answer(name="રમેશ"))  # "મહેશ નહીં, રમેશ", after hearing "આભાર, મહેશ."
    assert reply.line == f"બરાબર, રમેશ. {QUESTIONS['age'].ask}" and survey.answers.name == "રમેશ"
    for _ in range(MAX_WRONG_ANSWERS - 1):
        survey.respond(Reading("unclear"))
    assert not survey.finished


def test_a_wrong_answer_that_answers_a_later_question_keeps_that_answer(survey):
    survey.respond(answer(name="રમેશ"))
    reply = survey.respond(Reading("wrong_answer", {"village": "ખાંભા"}))  # asked the age
    assert reply.line == f"બરાબર, ખાંભા ગામ. {QUESTIONS['age'].ask}" and survey.answers.village == "ખાંભા"
    survey.respond(answer(age=40))
    assert survey.asked == "taluka"  # the village was given, so it isn't asked


def test_every_question_says_what_it_asked_in_its_own_words():
    for question in QUESTIONS.values():
        assert question.wrong not in (question.ask, question.again)


def test_the_wrong_answer_limit_can_be_changed(monkeypatch):
    survey = Survey(max_wrong=4)
    survey.opening()
    assert [survey.respond(Reading("unclear")).end for _ in range(4)] == [False, False, False, True]
    monkeypatch.setenv("SURVEY_MAX_WRONG_ANSWERS", "4")
    assert max_wrong_answers() == 4 and Survey.from_env().max_wrong == 4
    for bad in ("0", "three", "-2"):
        monkeypatch.setenv("SURVEY_MAX_WRONG_ANSWERS", bad)
        assert max_wrong_answers() == MAX_WRONG_ANSWERS
    monkeypatch.delenv("SURVEY_MAX_WRONG_ANSWERS")
    assert max_wrong_answers() == MAX_WRONG_ANSWERS
