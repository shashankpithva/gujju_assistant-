"""Gujarati numbers and times, and text rewritten for the voice."""

from datetime import time

import pytest

from agent.gujarati.numbers import (
    _WORDS,
    number_words,
    speak_time,
    spoken_number_text,
    to_ascii_digits,
    value_of,
)
from agent.gujarati.speech import for_the_ear, plain_punctuation, speak_gujarati
from agent.gujarati.style import check_line, repeated_openers
from agent.gujarati.understanding import has_gujarati, words


def test_every_number_up_to_99_has_its_own_word():
    assert len(_WORDS) == 100 and len(set(_WORDS)) == 100


@pytest.mark.parametrize(
    ("n", "said"),
    [
        (7, "સાત"), (19, "ઓગણીસ"), (29, "ઓગણત્રીસ"), (99, "નવ્વાણું"), (100, "સો"), (200, "બસો"),
        (380, "ત્રણસો એંસી"), (1000, "એક હજાર"), (1200, "બારસો"), (1250, "એક હજાર બસો પચાસ"),
        (100000, "એક લાખ"),
    ],
)  # fmt: skip
def test_number_words(n, said):
    assert number_words(n) == said


def test_number_words_are_read_back_as_numbers():
    assert value_of("ત્રણ") == 3 and value_of("પંદર") == 15 and value_of("ચારનું") == 4
    assert value_of("પાણી") is None and value_of("બસ") is None  # "just", not 200
    assert spoken_number_text("નવ આઠ ડબલ પાંચ") == "9 8 double 5"


def test_gujarati_digits_become_ascii():
    assert to_ascii_digits("૯૮૭૬૫ ૪૩૨૧૦") == "98765 43210"


@pytest.mark.parametrize(
    ("hour", "minute", "said"),
    [
        (19, 30, "સાંજે સાડા સાત વાગ્યે"),
        (6, 0, "સવારે છ વાગ્યે"),
        (8, 15, "સવારે સવા આઠ વાગ્યે"),
        (13, 30, "બપોરે દોઢ વાગ્યે"),  # never "સાડા એક"
        (14, 30, "બપોરે અઢી વાગ્યે"),  # never "સાડા બે"
        (20, 45, "રાત્રે પોણા નવ વાગ્યે"),
    ],
)
def test_times_are_said_the_gujarati_way(hour, minute, said):
    assert speak_time(time(hour, minute)) == said


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("દર 3 દિવસે, ઠીક છે.", "દર ત્રણ દિવસે, ઠીક છે."),
        ("1 કલાક, બરાબર.", "એક કલાક, બરાબર."),
        ("સાડા 3 કલાક", "સાડા ત્રણ કલાક"),
        ("45 મિનિટ", "પિસ્તાલીસ મિનિટ"),
        ("૨ કલાક", "બે કલાક"),
        ("સવારે 6-8 આવે છે.", "સવારે છ થી આઠ આવે છે."),
        ("7:30 PM એ.", "સાંજે સાડા સાત વાગ્યે એ."),
        ("નંબર 9876543210 છે.", "નંબર નવ આઠ સાત છ પાંચ, ચાર ત્રણ બે એક શૂન્ય છે."),
        ("હું AI આસિસ્ટન્ટ છું.", "હું એઆઈ આસિસ્ટન્ટ છું."),
        ("હા। બરાબર।", "હા. બરાબર."),
    ],
)
def test_text_is_rewritten_for_the_ear(text, said):
    assert for_the_ear(text) == said


def test_english_inside_a_word_is_left_alone():
    assert for_the_ear("rain") == "rain"  # holds "ai"


def test_the_voice_keeps_one_gender():
    assert for_the_ear("સારું, સમજી ગઈ.", "male") == "સારું, સમજી ગયો."
    assert for_the_ear("સારું, સમજી ગયો.", "female") == "સારું, સમજી ગઈ."


async def _stream(*chunks: str):
    for chunk in chunks:
        yield chunk


async def test_a_number_split_across_chunks_stays_whole():
    out = [c async for c in speak_gujarati("male")(_stream("દર 1", "5 દિવસે", " આવે છે."))]
    assert "".join(out) == "દર પંદર દિવસે આવે છે."


async def test_a_finished_sentence_goes_to_the_voice_at_once():
    stream = speak_gujarati("male")(_stream("સરસ, ખાંભા. ", "તાલુકો"))
    assert await anext(stream) == "સરસ, ખાંભા. "


def test_plain_punctuation_for_the_voice():
    assert plain_punctuation("ગામ — ખાંભા") == "ગામ, ખાંભા"
    assert plain_punctuation("‘હા’") == "'હા'"


def test_words_keeps_vowel_signs_and_the_virama():
    assert words("હા, બરાબર. જિલ્લો?") == ["હા", "બરાબર", "જિલ્લો"]
    assert has_gujarati("ok હા") and not has_gujarati("ok")


def test_the_style_rules_catch_written_gujarati():
    rules = {p.rule for p in check_line("કૃપા કરીને આપનું નામ જણાવશો?")}
    assert rules == {"bookish"}
    assert {p.rule for p in check_line("તું ક્યાં છે? અને ગામ?")} == {"intimate_pronoun", "two_questions"}
    assert repeated_openers(["સરસ, હા.", "સરસ, ના."]) == 1
