"""The survey's path through a call: one reading in, one line out."""

import pytest

from agent.places import gujarat
from agent.survey.answers import NOT_APPLICABLE, UNCLEAR
from agent.survey.flow import MAX_TURNS, Reading, Survey
from agent.survey.script import (
    BUSY,
    CHECK_IN,
    CONFIRMED,
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

YES = Reading("answer", confirm=True)
NO = Reading("answer", confirm=False)


def answer(**values) -> Reading:
    return Reading("answer", values)


@pytest.fixture
def survey() -> Survey:
    s = Survey(places=gujarat())
    s.opening()
    return s


def answer_places(survey: Survey) -> list[str]:
    """Village, taluka and district, each read back and confirmed."""
    return [
        survey.respond(answer(village="ખાંભા")).line,
        survey.respond(YES).line,
        survey.respond(answer(taluka="ખાંભા")).line,
        survey.respond(YES).line,
        survey.respond(answer(district="અમરેલી")).line,
        survey.respond(YES).line,
    ]


def answer_all(survey: Survey, *, water: bool = True) -> list[str]:
    lines = [survey.respond(answer(name="રમેશભાઈ પટેલ")).line, *answer_places(survey)]
    lines.append(survey.respond(answer(water_supply=water)).line)
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


def test_the_seven_questions_come_in_order_and_each_place_is_read_back_for_a_yes(survey):
    lines = answer_all(survey)
    assert lines[0] == f"આભાર, રમેશભાઈ પટેલ. {QUESTIONS['village'].ask}"
    assert lines[1] == "તમારું ગામ ખાંભા, બરાબર?"
    assert lines[2] == f"{CONFIRMED['village']} {QUESTIONS['taluka'].ask}"
    assert lines[3] == "ખાંભા તાલુકો, બરાબર?"
    assert lines[4] == f"{CONFIRMED['taluka']} {QUESTIONS['district'].ask}"
    assert lines[5] == "અમરેલી જિલ્લો, બરાબર?"
    assert lines[6] == f"{CONFIRMED['district']} {TO_WATER} {QUESTIONS['water_supply'].ask}"
    assert lines[7] == f"સારું. {QUESTIONS['frequency'].ask}"
    assert lines[8] == f"એકાંતરે, ઠીક છે. {QUESTIONS['duration'].ask}"
    assert lines[9].startswith("1 કલાક, બરાબર.") and RECORDED in lines[9] and lines[9].endswith("આવજો!")
    assert survey.status == "completed"


def test_the_last_answer_ends_the_call(survey):
    answer_all(survey)
    assert survey.finished
    assert survey.respond(answer(name="x")).end  # nothing more is asked


def test_the_sheet_gets_every_answer_written_out(survey):
    answer_all(survey)
    assert survey.sheet_values() == {
        "name": "રમેશભાઈ પટેલ",
        "village": "ખાંભા (Khambha)",  # the person's words, and the official name
        "taluka": "ખાંભા (Khambha)",
        "district": "અમરેલી (Amreli)",
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


def test_several_places_at_once_are_read_back_at_once(survey):
    survey.respond(answer(name="સીતા"))
    reply = survey.respond(answer(village="ધોળકા", taluka="ધોળકા", district="અમદાવાદ"))
    assert reply.line == "ધોળકા શહેર, ધોળકા તાલુકો અને અમદાવાદ જિલ્લો, બરાબર?"
    assert reply.changed == ()  # nothing goes in the sheet before the yes
    reply = survey.respond(YES)
    assert reply.line == f"{CONFIRMED['district']} {TO_WATER} {QUESTIONS['water_supply'].ask}"
    assert reply.changed == ("village", "taluka", "district")
    assert survey.sheet_values()["district"] == "અમદાવાદ (Ahmedabad)"


def test_how_often_said_with_yes_answers_both(survey):
    survey.respond(answer(name="a"))
    answer_places(survey)
    reply = survey.respond(answer(water_supply=True, frequency_days=1.0))
    assert reply.line == f"બરાબર, પાણી આવે છે અને રોજ. {QUESTIONS['duration'].ask}"


def test_how_often_alone_means_water_comes(survey):
    survey.respond(answer(name="a"))
    answer_places(survey)
    survey.respond(answer(frequency_days=2.0))  # "એકાંતરે આવે છે" to "does water come?"
    assert survey.answers.water_supply is True
    assert survey.asked == "duration"


def test_a_correction_to_an_earlier_place_is_read_back_and_the_question_stands(survey):
    survey.respond(answer(name="રમેશ"))
    survey.respond(answer(village="ખાંભા"))
    survey.respond(YES)
    reply = survey.respond(answer(village="ખંભાળિયા"))  # asked the taluka: "no, the village is..."
    assert reply.line == "તમારું શહેર ખંભાળિયા, બરાબર?"
    assert survey.answers.village == "ખાંભા (Khambha)"  # not until they say yes
    reply = survey.respond(YES)
    assert reply.line == f"{CONFIRMED['village']} {QUESTIONS['taluka'].ask}"
    assert survey.answers.village == "ખંભાળિયા (Khambhalia)" and survey.asked == "taluka"


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
    reply = survey.respond(answer(name="રમેશ", village="ખાંભા"))
    assert "name" not in survey.skipped and survey.answers.name == "રમેશ"
    assert reply.line == "આભાર, રમેશ. તમારું ગામ ખાંભા, બરાબર?"


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
    answer_places(survey)
    survey.respond(answer(water_supply=False))
    assert survey.status == "completed" and survey.note() == "Unclear: name"


def test_every_field_has_a_question():
    assert set(QUESTIONS) == set(FIELDS)


# Places: in the list, read back, and written only after a yes ------------------------------------


def at_village(survey: Survey) -> Survey:
    survey.respond(answer(name="રમેશ"))
    return survey


def test_a_place_goes_in_the_sheet_only_after_a_yes(survey):
    at_village(survey)
    reply = survey.respond(answer(village="ખાંભા"))
    assert reply.changed == () and survey.sheet_values()["village"] == ""
    assert survey.confirming and survey.pending == {"village": "ખાંભા"}
    reply = survey.respond(YES)
    assert reply.changed == ("village",) and survey.sheet_values()["village"] == "ખાંભા (Khambha)"


def test_no_to_a_place_read_back_asks_for_it_again(survey):
    at_village(survey)
    survey.respond(answer(village="ખાંભા"))
    reply = survey.respond(NO)
    assert reply.line == QUESTIONS["village"].again and reply.changed == ()
    assert survey.answers.village is None and survey.asked == "village" and not survey.confirming


def test_no_with_the_right_name_reads_that_one_back(survey):
    at_village(survey)
    survey.respond(answer(village="ખાંભા"))
    reply = survey.respond(Reading("answer", {"village": "ધારી"}, confirm=False))  # "ના, ધારી"
    assert reply.line == "તમારું ગામ ધારી, બરાબર?"
    survey.respond(YES)
    assert survey.answers.village == "ધારી (Dhari)"


def test_saying_the_name_again_is_a_yes(survey):
    at_village(survey)
    survey.respond(answer(village="ખાંભા"))
    reply = survey.respond(answer(village="ખંભા"))  # the same place, however it's spelt
    assert reply.line == f"{CONFIRMED['village']} {QUESTIONS['taluka'].ask}"
    assert survey.answers.village == "ખાંભા (Khambha)"


def test_another_name_for_a_place_is_read_back_as_the_lists(survey):
    at_village(survey)
    assert survey.respond(answer(village="બરોડા")).line == "તમારું શહેર વડોદરા, બરાબર?"
    survey.respond(YES)
    assert survey.answers.village == "વડોદરા (Vadodara)"
    survey.respond(answer(taluka="રાજપીપળા"))  # the taluka people call by its town
    assert survey.confirmation == "નાંદોદ તાલુકો, બરાબર?"


def test_a_place_that_isnt_in_the_list_is_asked_for_again_and_never_written(survey):
    at_village(survey)
    first = survey.respond(answer(village="પ્લાસ્ટિક")).line
    second = survey.respond(answer(village="કમ્પ્યુટર")).line
    third = survey.respond(answer(village="મોબાઈલ")).line
    assert first == QUESTIONS["village"].unlisted
    assert second == QUESTIONS["village"].again  # not the same line twice
    assert third == f"{MOVE_ON} {QUESTIONS['taluka'].ask}"
    assert survey.sheet_values()["village"] == UNCLEAR
    answer_rest = [answer(taluka="ખાંભા"), YES, answer(district="અમરેલી"), YES, answer(water_supply=False)]
    for reading in answer_rest:
        survey.respond(reading)
    assert survey.note() == "Village not in the list (heard: મોબાઈલ)"


def test_a_place_found_after_a_miss_is_taken(survey):
    at_village(survey)
    survey.respond(answer(village="પ્લાસ્ટિક"))
    assert survey.respond(answer(village="ખાંભા")).line == "તમારું ગામ ખાંભા, બરાબર?"
    survey.respond(YES)
    assert survey.answers.village == "ખાંભા (Khambha)" and "Village" not in survey.note()


def test_yes_to_one_place_and_a_new_name_for_another(survey):
    at_village(survey)
    survey.respond(answer(village="ખાંભા", taluka="ખાંભા"))
    reply = survey.respond(Reading("answer", {"taluka": "ધારી"}, confirm=True))  # "હા, પણ તાલુકો ધારી"
    assert reply.line == f"{CONFIRMED['village']} ધારી તાલુકો, બરાબર?"
    assert survey.answers.village == "ખાંભા (Khambha)" and survey.answers.taluka is None


def test_anything_else_while_a_place_is_read_back_reads_it_back_again(survey):
    at_village(survey)
    survey.respond(answer(village="ખાંભા"))
    assert survey.respond(Reading("repeat")).line == "તમારું ગામ ખાંભા, બરાબર?"
    assert survey.respond(Reading("acknowledge")).line == "તમારું ગામ ખાંભા, બરાબર?"  # "હા" to a check-in
    assert survey.respond(Reading("wait")).line == WAITING
    assert not survey.confirming  # a "હા" when they're back is not a yes to the place
    assert survey.respond(YES).line == "તમારું ગામ ખાંભા, બરાબર?"
    assert survey.answers.village is None
    assert survey.didnt_hear() == "તમારું ગામ ખાંભા, બરાબર?"
    survey.respond(YES)
    assert survey.answers.village == "ખાંભા (Khambha)"


def test_a_hang_up_before_the_yes_writes_nothing(survey):
    at_village(survey)
    survey.respond(answer(village="ખાંભા"))
    assert survey.end() == "partial"
    assert survey.sheet_values()["village"] == ""
    assert (
        survey.note() == "Call ended at the village question; Village not confirmed (heard: ખાંભા (Khambha))"
    )


def test_what_is_known_picks_which_place_of_a_name_is_meant(survey):
    at_village(survey)
    survey.respond(answer(village="કલોલ"))
    survey.respond(YES)
    survey.respond(answer(taluka="કાલોલ"))  # Kalol, in Panch Mahals or in Gandhinagar
    survey.respond(YES)
    assert survey.answers.taluka == "કાલોલ (Kalol)"
    reply = survey.respond(answer(district="ગાંધીનગર"))
    reply = survey.respond(YES)
    assert survey.answers.taluka == "કલોલ (Kalol Gandhinagar)" and "taluka" in reply.changed


def test_places_that_dont_go_together_are_noted(survey):
    at_village(survey)
    for reading in (answer(village="ખાંભા"), YES, answer(taluka="ગોંડલ"), YES, answer(district="અમરેલી"), YES):
        survey.respond(reading)
    survey.respond(answer(water_supply=False))
    assert survey.note() == (
        "Check: no Khambha in Gondal taluka in the list; "
        "Check: Gondal taluka is in Rajkot district, not Amreli"
    )


def test_without_the_list_any_name_is_read_back_and_needs_a_yes():
    survey = Survey()
    survey.opening()
    survey.respond(answer(name="રમેશ"))
    assert survey.respond(answer(village="નવું નગર")).line == "તમારું ગામ નવું નગર, બરાબર?"
    survey.respond(YES)
    assert survey.answers.village == "નવું નગર"
