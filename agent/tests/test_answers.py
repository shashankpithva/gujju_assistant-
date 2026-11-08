"""Reading answers without the LLM, and writing them for the sheet and the voice."""

import pytest

from agent.survey.answers import (
    asks_to_repeat,
    clean_days,
    clean_minutes,
    clean_note,
    clean_text,
    days_from,
    duration_text,
    frequency_text,
    is_busy,
    minutes_from,
    says_goodbye,
    yes_or_no,
)


@pytest.mark.parametrize(
    ("said", "comes"),
    [
        ("હા", True),
        ("હા, આવે છે", True),
        ("આવે છે ને", True),
        ("હાજી", True),
        ("Yes", True),
        ("ના", False),
        ("ના, નથી આવતું", False),
        ("નથી આવતું", False),
        ("બિલકુલ નથી આવતું", False),
        ("ના જી", False),  # "જી" is respect, not yes
    ],
)
def test_a_plain_yes_or_no_is_read_without_the_llm(said, comes):
    assert yes_or_no(said, strict=True) is comes


@pytest.mark.parametrize("said", ["ના આવે", "જી", "ક્યારેક આવે", "હા પણ ઓછું", ""])
def test_anything_less_plain_goes_to_the_llm(said):
    assert yes_or_no(said, strict=True) is None


def test_the_fallback_reads_more_loosely():
    assert yes_or_no("ક્યારેક આવે", strict=False) is True
    assert yes_or_no("ના આવે", strict=False) is None  # both: still not a guess


@pytest.mark.parametrize(
    ("said", "days"),
    [
        ("રોજ", 1),
        ("દરરોજ આવે છે", 1),
        ("daily", 1),
        ("એકાંતરે", 2),
        ("બે દિવસે", 2),
        ("દર ત્રણ દિવસે", 3),
        ("3 દિવસે એક વાર", 3),
        ("૪ દિવસે", 4),  # Gujarati digits
        ("15 દિવસે", 15),
        ("અઠવાડિયે એક વાર", 7),
        ("અઠવાડિયામાં બે વાર", 3.5),
        ("મહિને", 30),
        ("દિવસમાં બે વાર", 1),  # twice a day is still every day
        ("એક દિવસ છોડીને", 2),
        ("બે", 2),  # the answer to "how many days?"
    ],
)
def test_how_often(said, days):
    assert days_from(said, strict=True) == days


@pytest.mark.parametrize("said", ["રોજ સવારે", "ખબર નથી", "બે વાર", "નક્કી નહીં", ""])
def test_how_often_that_isnt_plain_goes_to_the_llm(said):
    assert days_from(said, strict=True) is None


@pytest.mark.parametrize(
    ("said", "minutes"),
    [
        ("એક કલાક", 60),
        ("અડધો કલાક", 30),
        ("પોણો કલાક", 45),
        ("સવા કલાક", 75),
        ("દોઢ કલાક", 90),
        ("અઢી કલાક", 150),
        ("સાડા ત્રણ કલાક", 210),
        ("પોણા બે કલાક", 105),
        ("45 મિનિટ", 45),
        ("દસ મિનિટ માંડ", 10),
        ("એક કલાક ત્રીસ મિનિટ", 90),
        ("2કલાક", 120),  # no space between the number and its unit
        ("લગભગ અડધો કલાક", 30),
        ("half an hour", 30),
        ("આખો દિવસ", 1440),
        ("24 કલાક", 1440),
    ],
)
def test_how_long(said, minutes):
    assert minutes_from(said, strict=True) == minutes


@pytest.mark.parametrize("said", ["સવારે 6 થી 8", "બે", "એક મિનિટ", "બે મિનિટ", "થોડી વાર", ""])
def test_how_long_that_isnt_plain_goes_to_the_llm(said):
    # "એક મિનિટ" alone is "hold on" far more often than a one-minute water supply.
    assert minutes_from(said, strict=True) is None


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("મારું નામ રમેશ પટેલ છે", "રમેશ પટેલ"),
        ("હું રમેશ બોલું છું", "રમેશ"),
        ("રમેશભાઈ", "રમેશભાઈ"),  # ભાઈ stays: the person said it
        ("મારું ગામ ખાંભા છે", "ખાંભા"),
        ("ખાંભા ગામ", "ખાંભા"),
        ("અમરેલી જિલ્લો.", "અમરેલી"),
        ("Ramesh Patel.", "Ramesh Patel"),
    ],
)
def test_names_and_places_lose_their_filler(raw, clean):
    assert clean_text(raw) == clean


@pytest.mark.parametrize("raw", ["શું?", "હા બોલો", "null", "unknown", "", "  ", None, 42, "ખબર નથી"])
def test_what_isnt_a_name_or_place_is_dropped(raw):
    assert clean_text(raw) is None


def test_numbers_are_checked():
    assert clean_days(2) == 2.0 and clean_days("3") == 3.0 and clean_days(0.5) == 1.0
    assert clean_days(0) is None and clean_days(90) is None and clean_days(True) is None
    assert clean_minutes(30.4) == 30 and clean_minutes("૬૦") == 60
    assert clean_minutes(0) is None and clean_minutes(2000) is None and clean_minutes("half") is None
    assert clean_note("  નક્કી   નહીં ") == "નક્કી નહીં" and clean_note("null") is None


@pytest.mark.parametrize(
    ("days", "said", "written"),
    [
        (1, "રોજ", "રોજ"),
        (2, "એકાંતરે", "એકાંતરે (દર 2 દિવસે)"),
        (3, "દર 3 દિવસે", "દર 3 દિવસે"),
        (7, "અઠવાડિયે એક વાર", "અઠવાડિયે એક વાર (દર 7 દિવસે)"),
        (3.5, "અઠવાડિયામાં 2 વાર", "અઠવાડિયામાં 2 વાર (દર 3.5 દિવસે)"),
        (30, "મહિને એક વાર", "મહિને એક વાર (દર 30 દિવસે)"),
    ],
)
def test_how_often_is_said_and_written_the_gujarati_way(days, said, written):
    assert frequency_text(days) == said
    assert frequency_text(days, written=True) == written


@pytest.mark.parametrize(
    ("minutes", "said", "written"),
    [
        (10, "10 મિનિટ", "10 મિનિટ"),
        (30, "અડધો કલાક", "અડધો કલાક (30 મિનિટ)"),
        (60, "1 કલાક", "1 કલાક (60 મિનિટ)"),
        (90, "દોઢ કલાક", "દોઢ કલાક (90 મિનિટ)"),
        (150, "અઢી કલાક", "અઢી કલાક (150 મિનિટ)"),
        (210, "સાડા 3 કલાક", "સાડા 3 કલાક (210 મિનિટ)"),
        (100, "1 કલાક 40 મિનિટ", "1 કલાક 40 મિનિટ (100 મિનિટ)"),
        (1440, "આખો દિવસ", "આખો દિવસ"),
    ],
)
def test_how_long_is_said_and_written_the_gujarati_way(minutes, said, written):
    assert duration_text(minutes) == said
    assert duration_text(minutes, written=True) == written


def test_a_note_stands_in_for_a_number():
    assert frequency_text(None, "નક્કી નહીં") == "નક્કી નહીં"
    assert duration_text(None, None) is None


@pytest.mark.parametrize("said", ["શું?", "ફરીથી બોલો", "સંભળાયું નહીં", "હેં?", "what?"])
def test_asking_to_hear_it_again(said):
    assert asks_to_repeat(said)


@pytest.mark.parametrize("said", ["શું નામ?", "હા", "રમેશ", ""])
def test_other_words_arent_a_repeat_request(said):
    assert not asks_to_repeat(said)


@pytest.mark.parametrize("said", ["હું બિઝી છું", "પછી ફોન કરજો", "અત્યારે ટાઈમ નથી", "I'm busy"])
def test_busy(said):
    assert is_busy(said)


def test_goodbyes():
    assert says_goodbye("આવજો") and says_goodbye("ચાલો ફોન મૂકું છું") and says_goodbye("ok bye")
    assert not says_goodbye("આવે છે") and not says_goodbye("ફોન નંબર")
