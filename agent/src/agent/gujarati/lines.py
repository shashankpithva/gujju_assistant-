"""Every fixed line the agent says on a Gujarati call, written for the ear.

These were written as Gujarati, not translated from tools.py: "ભરાઈ ગયું", "સામેથી ફોન કરશે" and
"ફાવશે?" have no word-for-word English source. Lines avoid first-person verbs that change with the
speaker's gender (સમજી ગયો / સમજી ગઈ), so the same text fits any voice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from agent.gujarati import numbers as gu

Gender = Literal["male", "female"]

FILLERS = ("એક મિનિટ.", "જોઉં છું, એક સેકન્ડ.", "હા, જોઈ લઉં.")
READ_BACK = ("તો ફરી એક વાર કહી દઉં:", "એક વાર ચેક કરી લઉં:")
ANYTHING_ELSE = ("બીજું કંઈ મદદ કરું?", "બીજું કંઈ જોઈએ છે?")

# First the question, then how to ask again when the answer didn't give it. The last sentence must
# hold the word for what's asked (નામ, નંબર): turn_taking.py reads it to wait longer for the answer.
ASK = {
    "party_size": ("કેટલા લોકો માટે જોઈએ છે?", "માફ કરજો, કેટલા જણ આવશો?"),
    "day_and_time": ("કયા દિવસે અને કેટલા વાગ્યે આવવું છે?", "માફ કરજો, કયો દિવસ અને કેટલા વાગ્યે?"),
    "day": ("કયા દિવસે આવવું છે?", "માફ કરજો, કયો દિવસ કહ્યો?"),
    "time": ("{day} કેટલા વાગ્યે આવશો?", "માફ કરજો, {day} કેટલા વાગ્યે?"),
    "name": ("કયા નામે બુક કરું?", "માફ કરજો, બરાબર સંભળાયું નહીં. તમારું નામ ફરીથી કહેશો?"),
    "phone": ("તમારો ફોન નંબર કહેશો?", "માફ કરજો, બરાબર ના સંભળાયું. નંબર એક એક આંકડો કરીને કહેશો?"),
}

# Said in place of a sentence the reply guard stopped (guard.py).
NOT_DONE_YET = "માફ કરજો, એ હજી થયું નથી. કરી દઉં?"
NO_SUCH_CODE = "માફ કરજો, એનો બુકિંગ કોડ હજી મારી પાસે નથી."
NO_SUCH_PRICE = "માફ કરજો, એનો ભાવ મારી પાસે નથી."

CHECK_IN = "હેલો, તમે લાઇન પર છો?"
SILENCE_GOODBYE = "સારું, ફોન મૂકું છું. ફરી ફોન કરજો, આવજો!"
TIME_UP_GOODBYE = "માફ કરજો, હવે આ કૉલ પૂરો કરવો પડશે. બીજું કંઈ હોય તો ફરી ફોન કરજો. આવજો!"
NOT_SET_UP = "માફ કરજો, આ નંબર હજી ચાલુ થયો નથી. થોડી વાર પછી ફોન કરજો. આવજો!"
API_DOWN = "માફ કરજો, અત્યારે બુકિંગ સિસ્ટમ ખૂલતી નથી. થોડી મિનિટ પછી ફરી ફોન કરજો. આવજો!"


def with_suffix(name: str, suffix: str) -> str:
    """A Gujarati postposition joins a Gujarati word and stands apart from a Latin one: "આશાના", "Asha ના"."""
    return f"{name} {suffix}" if name[-1:].isascii() else f"{name}{suffix}"


def party(size: int) -> str:
    """ચાર જણ."""
    return f"{gu.number_words(size)} જણ"


def greeting(restaurant_name: str, own_greeting: str, *, recording: bool) -> str:
    """Who we are, that this is an AI, how to reach staff, and the recording notice, in as few words
    as those allow: the caller waits through all of it. A greeting staff wrote in Gujarati is used
    as it stands; the English default isn't, as the caller would hear English first."""
    is_gujarati = any("઀" <= ch <= "૿" for ch in own_greeting)
    opening = own_greeting if is_gujarati else f"નમસ્તે, {with_suffix(restaurant_name, 'માંથી')} બોલું છું."
    parts = [opening, "હું AI આસિસ્ટન્ટ છું, અને સ્ટાફ માટે મેસેજ પણ લઈ શકું છું."]
    if recording:
        parts.append("આ કૉલ રેકોર્ડ થાય છે.")
    parts.append("બોલો, શું મદદ કરું?")
    return " ".join(parts)


@dataclass(frozen=True)
class GujaratiLines:
    """The lines tools.py says on a Gujarati call. `gender` is the voice's: see speech.py."""

    gender: Gender = "male"

    def when(self, start: datetime, today: date) -> str:
        """મંગળવારે સાંજે સાડા સાત વાગ્યે."""
        return f"{gu.speak_day(start.date(), today)} {gu.speak_time(start)}"

    def describe(self, size: int, name: str, start: datetime, today: date) -> str:
        return f"{self.when(start, today)}, {party(size)} માટે, {with_suffix(name, 'ના')} નામે ટેબલ"

    def free(self, size: int, start: datetime, today: date) -> str:
        return f"સરસ, {self.when(start, today)} {party(size)} માટે ટેબલ મળી જશે."

    def taken(self, at: datetime, same_day: list[datetime], other_days: list[str]) -> str:
        offers = [gu.join_times(same_day)] if same_day else []
        return f"માફ કરજો, {gu.speak_time(at)} જગ્યા નથી. {gu.join_or(offers + other_days)} ફાવશે?"

    def fully_booked(self, day: date, today: date) -> str:
        return f"માફ કરજો, {gu.speak_day(day, today)} બધું ભરાઈ ગયું છે. બીજો કોઈ દિવસ ફાવશે?"

    def goodbye(self, restaurant_name: str, booked_on: date | None, today: date) -> str:
        if booked_on:
            return f"ફોન કરવા બદલ આભાર. {gu.speak_day(booked_on, today)} મળીએ, આવજો!"
        return f"{with_suffix(restaurant_name, 'માં')} ફોન કરવા બદલ આભાર. આવજો!"

    def phone_retry(self, heard: str) -> str:
        if not heard:
            return ASK["phone"][1]
        count = gu.number_words(len(heard))
        if len(heard) < 10:
            return f"માફ કરજો, {count} આંકડા જ સંભળાયા: {gu.speak_digits(heard)}. આખો નંબર ફરીથી કહેશો?"
        return f"માફ કરજો, આ તો {count} આંકડા થયા. નંબર ફરીથી કહેશો?"

    def read_back_booking(self, lead: str, details: str, phone: str | None, notes: str | None) -> str:
        if phone:
            details += f", નંબર {phone}"
        if notes:
            details += f", અને નોંધ: {notes}"
        return f"{lead} {details}. બુક કરી દઉં?"

    def read_back_change(self, lead: str, old: str, new: str) -> str:
        return f"{lead} {old} હતું, એ બદલીને {new} કરી દઉં. બરાબર?"

    def read_back_cancel(self, booking: str) -> str:
        return f"તો {booking} કેન્સલ કરવું છે, બરાબર?"

    def booked(self, code: str) -> str:
        return f"થઈ ગયું! તમારો બુકિંગ કોડ છે: {code}."

    def changed(self, booking: str, code: str) -> str:
        return f"થઈ ગયું, હવે {booking} છે. તમારો કોડ એ જ છે: {code}."

    def cancelled(self) -> str:
        return "થઈ ગયું, તમારું બુકિંગ કેન્સલ કરી દીધું છે."

    def message_taken(self) -> str:
        return "મેનેજરને મેસેજ આપી દીધો છે, એ તમને સામેથી ફોન કરશે."
