"""Numbers from the sheet, however they were typed or pasted."""

import pytest

from agent.phone import masked, normalize_phone, pretty


@pytest.mark.parametrize(
    ("raw", "e164"),
    [
        ("9876543210", "+919876543210"),
        ("98765 43210", "+919876543210"),
        ("+91 98765-43210", "+919876543210"),
        ("09876543210", "+919876543210"),
        ("919876543210", "+919876543210"),
        ("0091 98765 43210", "+919876543210"),
        ("૯૮૭૬૫૪૩૨૧૦", "+919876543210"),  # Gujarati digits
        ("9.87654321E+09", "+919876543210"),  # a cell the spreadsheet turned into a number
        ("+1 415 555 0123", "+14155550123"),
    ],
)
def test_numbers_become_e164(raw, e164):
    assert normalize_phone(raw) == e164


@pytest.mark.parametrize("raw", ["", "12345", "not a number", "+12", "(test call)"])
def test_what_isnt_a_number_is_refused(raw):
    assert normalize_phone(raw) is None


def test_another_country_code(monkeypatch):
    monkeypatch.setenv("DEFAULT_COUNTRY_CODE", "+1")
    assert normalize_phone("4155550123") == "+14155550123"


def test_numbers_for_people_and_for_logs():
    assert pretty("+919876543210") == "+91 98765 43210"
    assert pretty("+14155550123") == "+1 415 555 0123"
    assert masked("+919876543210") == "+9198xxxxx210"
    assert masked(None) == "-"
