"""Gujarati calls through the real tools: every line the caller hears is checked for English."""

import re
from unittest.mock import patch

import pytest
from livekit.agents import ToolResult

from agent.api_client.sample import RESTAURANT_ID
from agent.call_limits import CallLimits
from agent.gujarati import lines
from agent.gujarati.lines import GujaratiLines
from agent.tools import CallState, Receptionist, new_call_id

from .conftest import turn

CALLER = "+919876543210"
_ENGLISH_WORD = re.compile(r"[A-Za-z]{2,}")


def assert_gujarati(line: str) -> None:
    """No English word reaches the caller, apart from a name that's written that way."""
    stray = set(_ENGLISH_WORD.findall(line)) - {"AI", "Asha", "Rao", "Aman", "The", "Saffron", "Table"}
    assert not stray, line


@pytest.fixture
def state(api, restaurant) -> CallState:
    return CallState(
        api=api,
        restaurant=restaurant,
        call_id=new_call_id(),
        caller_phone=CALLER,
        language="gu",
        gu=GujaratiLines("male"),
    )


@pytest.fixture
def agent(state) -> Receptionist:
    return Receptionist(state)


def run_turn(state: CallState, speech_id: str):
    return turn(state, speech_id)


async def test_a_booking_given_bit_by_bit_in_gujarati(agent, state, api):
    said = []

    async def step(speech_id: str, **details):
        context = run_turn(state, speech_id)
        result = await agent.prepare_booking(context, **details)
        assert isinstance(result, ToolResult), result
        line = context.session.said[-1]
        assert_gujarati(line)
        said.append(line)
        return line

    assert await step("t1") == lines.ASK["party_size"][0]
    assert await step("t2", party_size=4) == lines.ASK["day_and_time"][0]
    assert await step("t3", day="મંગળવારે") == lines.ASK["time"][0].format(day="મંગળવારે")
    free = await step("t4", time="19:30")
    assert free == "સરસ, મંગળવારે સાંજે સાડા સાત વાગ્યે ચાર જણ માટે ટેબલ મળી જશે. કયા નામે બુક કરું?"
    read_back = await step("t5", guest_name="આશા")
    assert "મંગળવારે સાંજે સાડા સાત વાગ્યે, ચાર જણ માટે, આશાના નામે ટેબલ" in read_back
    assert read_back.endswith("બુક કરી દઉં?")
    assert state.pending is not None

    context = run_turn(state, "t6")
    await agent.confirm_action(context)
    done = context.session.said[-1]
    assert_gujarati(done)
    assert done.startswith("થઈ ગયું! તમારો બુકિંગ કોડ છે:")
    assert state.outcomes == ["booked"]
    saved = (await api.find_reservations(RESTAURANT_ID, phone=CALLER)).reservations
    assert len(saved) == 1 and saved[0].guest_name == "આશા" and saved[0].party_size == 4
    assert f"{saved[0].start:%Y-%m-%d %H:%M}" == "2026-10-27 19:30"


async def test_the_booking_code_is_spelled_in_gujarati(agent, state, api):
    await agent.prepare_booking(
        run_turn(state, "t1"), party_size=2, day="મંગળવારે", time="20:00", guest_name="Asha"
    )
    context = run_turn(state, "t2")
    await agent.confirm_action(context)
    code = state.made_codes[0]
    assert all(ch not in context.session.said[-1] for ch in code if ch.isalpha())


async def test_a_full_slot_offers_the_nearest_times_in_gujarati(agent, state):
    context = run_turn(state, "t1")
    await agent.prepare_booking(context, party_size=4, day="31 તારીખે", time="19:30")
    line = context.session.said[-1]
    assert_gujarati(line)
    assert line.startswith("માફ કરજો, સાંજે સાડા સાત વાગ્યે જગ્યા નથી.")
    assert line.endswith("ફાવશે?")


async def test_a_short_phone_number_is_asked_for_again_in_gujarati(api, restaurant):
    state = CallState(
        api=api, restaurant=restaurant, call_id=new_call_id(), language="gu", gu=GujaratiLines("male")
    )
    agent = Receptionist(state)
    await agent.prepare_booking(
        run_turn(state, "t1"), party_size=2, day="મંગળવારે", time="20:00", guest_name="આશા"
    )
    context = run_turn(state, "t2")
    await agent.prepare_booking(context, phone_number="નવ આઠ સાત")
    line = context.session.said[-1]
    assert_gujarati(line)
    assert "ત્રણ આંકડા જ સંભળાયા: નવ આઠ સાત" in line
    assert state.given_phone is None


async def test_a_spoken_gujarati_number_is_read_back_digit_by_digit(api, restaurant):
    state = CallState(
        api=api, restaurant=restaurant, call_id=new_call_id(), language="gu", gu=GujaratiLines("male")
    )
    agent = Receptionist(state)
    await agent.prepare_booking(
        run_turn(state, "t1"), party_size=2, day="મંગળવારે", time="20:00", guest_name="આશા"
    )
    context = run_turn(state, "t2")
    await agent.prepare_booking(context, phone_number="નવ આઠ સાત છ પાંચ ચાર ત્રણ બે એક શૂન્ય")
    assert state.given_phone == "+919876543210"
    assert "નંબર નવ આઠ સાત છ પાંચ, ચાર ત્રણ બે એક શૂન્ય" in context.session.said[-1]


async def test_change_and_cancel_are_read_back_in_gujarati(agent, state):
    await agent.prepare_booking(
        run_turn(state, "t1"), party_size=2, day="મંગળવારે", time="20:00", guest_name="આશા"
    )
    await agent.confirm_action(run_turn(state, "t2"))
    code = state.made_codes[0]

    context = run_turn(state, "t3")
    await agent.prepare_change(context, code, new_time="20:30")
    line = context.session.said[-1]
    assert_gujarati(line)
    assert "રાત્રે સાડા આઠ વાગ્યે" in line and line.endswith("બરાબર?")

    context = run_turn(state, "t4")
    await agent.confirm_action(context)
    assert_gujarati(context.session.said[-1])
    assert context.session.said[-1].startswith("થઈ ગયું, હવે")

    context = run_turn(state, "t5")
    await agent.prepare_cancel(context, code)
    assert_gujarati(context.session.said[-1])
    assert "કેન્સલ કરવું છે" in context.session.said[-1]

    context = run_turn(state, "t6")
    await agent.confirm_action(context)
    assert_gujarati(context.session.said[-1])
    assert state.outcomes == ["booked", "changed", "cancelled"]


async def test_a_message_is_confirmed_in_gujarati_not_with_the_apis_english(agent, state):
    context = run_turn(state, "t1")
    await agent.take_message(context, "આશા", "large_party", "પંદર જણ માટે પાર્ટી")
    line = context.session.said[-1]
    assert_gujarati(line)
    assert "manager" not in line.lower()


async def test_the_goodbye_is_gujarati_and_mentions_the_booked_day(agent, state):
    await agent.prepare_booking(
        run_turn(state, "t1"), party_size=2, day="મંગળવારે", time="20:00", guest_name="આશા"
    )
    await agent.confirm_action(run_turn(state, "t2"))

    context = run_turn(state, "t3")
    context.session.history.add_message(role="user", content="આવજો")
    await agent.end_call(context)
    assert context.session.said[-1] == "ફોન કરવા બદલ આભાર. મંગળવારે મળીએ, આવજો!"


async def test_end_call_is_refused_until_the_caller_is_done(agent, state):
    context = run_turn(state, "t1")
    context.session.history.add_message(role="assistant", content="બુક કરી દઉં?")
    context.session.history.add_message(role="user", content="ના")
    assert "hasn't said goodbye" in await agent.end_call(context)


async def test_fillers_on_a_slow_lookup_are_gujarati(agent, state):
    import asyncio

    context = run_turn(state, "t1")

    async def slow():
        await asyncio.sleep(0.05)
        return "done"

    with patch("agent.tools.FILLER_AFTER_SECONDS", 0.0):
        await agent._waiting(context, slow())
    assert context.session.said[0] in lines.FILLERS


async def test_every_call_limit_line_is_gujarati():
    class Session:
        def __init__(self):
            self.said = []

        async def interrupt(self, force=False):
            pass

        async def say(self, text, **_):
            self.said.append(text)

        def shutdown(self):
            pass

    class Ctx:
        async def delete_room(self):
            pass

        def shutdown(self, reason=""):
            pass

    session = Session()
    limits = CallLimits(session, Ctx(), max_call_seconds=0, silence_grace_seconds=0, language="gu")
    await limits._check_in_then_hang_up()
    assert session.said == [lines.CHECK_IN, lines.SILENCE_GOODBYE]

    session = Session()
    limits = CallLimits(session, Ctx(), max_call_seconds=0, language="gu")
    await limits._end_at_time_limit()
    assert session.said == [lines.TIME_UP_GOODBYE]


def test_the_call_log_records_gujarati(state):
    from datetime import UTC, datetime

    from agent.call_log import build_call_log
    from agent.metrics import LatencyTracker

    now = datetime.now(UTC)
    log = build_call_log(
        state,
        LatencyTracker(llm_model="x"),
        channel="phone",
        dialed_number="+14155550123",
        started_at=now,
        ended_at=now,
    )
    assert log.language == "gu"


async def test_facts_ask_the_api_for_gujarati_wording(api, restaurant):
    from agent.facts import load_facts

    asked = []
    real = api.get_info

    async def spy(restaurant_id, topic, language="en"):
        asked.append(language)
        return await real(restaurant_id, topic, language)

    api.get_info = spy
    await load_facts(api, restaurant, "gu")
    assert set(asked) == {"gu"}


def test_an_english_call_has_no_gujarati_lines(api, restaurant):
    state = CallState(api=api, restaurant=restaurant, call_id="x")
    assert state.gu is None and state.language == "en"
