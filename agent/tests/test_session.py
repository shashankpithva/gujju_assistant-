"""The survey agent in a real LiveKit AgentSession (text only), with a scripted LLM reading answers.

These go through LiveKit's own turn pipeline, so they check what a call does, not only what the
flow decides: every line comes from the script, the goodbye can't be cut off, and the agent keeps
going after the name, which is where the old receptionist lost its way.
"""

import time

import pytest
from livekit.agents import AgentSession, StopResponse
from livekit.agents.llm import ChatContext, ChatMessage

from agent.places import gujarat
from agent.survey.agent import SurveyAgent, last_agent_line, words_since_agent_spoke
from agent.survey.flow import Survey
from agent.survey.reader import AnswerReader
from agent.survey.script import BUSY, CONFIRMED, QUESTIONS, RECORDED, TO_WATER
from tests.conftest import ScriptedLLM

ANSWERS = {
    "હા બોલો": {"intent": "acknowledge"},
    "મારું નામ રમેશભાઈ પટેલ": {"intent": "answer", "name": "રમેશભાઈ પટેલ"},
    "રમેશ": {"intent": "answer", "name": "રમેશ"},
    "ખાંભા": {"intent": "answer", "village": "ખાંભા"},
    "ખાંભા જ": {"intent": "answer", "taluka": "ખાંભા"},
    "અમરેલી": {"intent": "answer", "district": "અમરેલી"},
    "અત્યારે ટાઈમ નથી, પછી ફોન કરજો": {"intent": "busy"},
}


async def converse(said: list[str], *, survey: Survey | None = None, model: ScriptedLLM | None = None):
    """Run the opening, then each thing the person says; returns the agent's reply to each."""
    survey = survey or Survey(places=gujarat())
    model = model or ScriptedLLM(ANSWERS)
    goodbyes = []
    agent = SurveyAgent(survey, AnswerReader(model), on_goodbye=goodbyes.append)
    replies: list[list[str]] = []
    async with AgentSession(llm=model) as session:
        await session.start(agent)
        intro, question = survey.opening()
        await session.say(intro)
        await session.say(question)
        agent.start_listening()
        for words in said:
            result = await session.run(user_input=words)
            replies.append([e.item.text_content for e in result.events if e.type == "message"])
    return survey, replies, goodbyes, model


async def test_a_whole_survey_from_name_to_goodbye():
    survey, replies, goodbyes, model = await converse(
        [
            "હા બોલો",
            "મારું નામ રમેશભાઈ પટેલ",
            "ખાંભા",
            "હા",
            "ખાંભા જ",
            "હા બરાબર",
            "અમરેલી",
            "હા",
            "હા આવે છે",
            "એકાંતરે",
            "એક કલાક",
        ]
    )
    assert replies[0] == [QUESTIONS["name"].ask]
    assert replies[1] == [f"આભાર, રમેશભાઈ પટેલ. {QUESTIONS['village'].ask}"]
    assert replies[2] == ["તમારું ગામ ખાંભા, બરાબર?"]
    assert replies[3] == [f"{CONFIRMED['village']} {QUESTIONS['taluka'].ask}"]
    assert replies[4] == ["ખાંભા તાલુકો, બરાબર?"]
    assert replies[6] == ["અમરેલી જિલ્લો, બરાબર?"]
    assert replies[7] == [f"{CONFIRMED['district']} {TO_WATER} {QUESTIONS['water_supply'].ask}"]
    assert replies[10][0].startswith("1 કલાક, બરાબર.") and RECORDED in replies[10][0]
    assert survey.status == "completed" and len(goodbyes) == 1
    assert survey.sheet_values()["district"] == "અમરેલી (Amreli)"
    # Names and places went to the LLM; each "હા", "એકાંતરે" and "એક કલાક" didn't need it.
    assert len(model.requests) == 5


async def test_after_the_name_the_survey_goes_straight_on():
    # The reported bug: after the name, the old agent stalled. Here the next question always comes.
    survey, replies, _, _ = await converse(["રમેશ", "ખાંભા"])
    assert replies == [[f"આભાર, રમેશ. {QUESTIONS['village'].ask}"], ["તમારું ગામ ખાંભા, બરાબર?"]]
    assert survey.confirming


async def test_after_the_name_an_unclear_answer_gets_the_question_again():
    survey, replies, _, _ = await converse(["રમેશ", "ઉમ્મ"])
    assert replies[1] == [QUESTIONS["village"].again]


async def test_the_llm_being_down_doesnt_stop_the_survey():
    survey, replies, _, _ = await converse(["રમેશ", "ખાંભા", "હા"], model=ScriptedLLM(fail=True))
    assert replies[0] == [f"આભાર, રમેશ. {QUESTIONS['village'].ask}"]
    assert replies[1] == ["તમારું ગામ ખાંભા, બરાબર?"]
    assert survey.answers.village == "ખાંભા (Khambha)"


async def test_the_goodbye_is_said_whole_and_ends_the_call():
    survey, replies, goodbyes, _ = await converse(["અત્યારે ટાઈમ નથી, પછી ફોન કરજો"])
    assert replies[0] == [BUSY] and survey.status == "busy"
    (goodbye,) = goodbyes
    assert goodbye.allow_interruptions is False  # a "હેલો?" over it can't cut it short


async def test_nothing_is_said_after_the_survey_has_ended():
    survey, replies, _, _ = await converse(["અત્યારે ટાઈમ નથી, પછી ફોન કરજો", "રમેશ"])
    assert replies[1] == []


async def test_a_hello_over_the_introduction_is_not_taken_as_an_answer():
    agent = SurveyAgent(Survey(), AnswerReader(None))
    hello = ChatMessage(role="user", content=["હેલો?"], metrics={"started_speaking_at": time.time()})
    with pytest.raises(StopResponse):  # the introduction hasn't finished
        await agent.on_user_turn_completed(ChatContext(), hello)
    agent.start_listening()
    with pytest.raises(StopResponse):  # began before it finished
        await agent.on_user_turn_completed(ChatContext(), hello)
    answer = ChatMessage(role="user", content=["રમેશ"], metrics={"started_speaking_at": time.time() + 1})
    await agent.on_user_turn_completed(ChatContext(), answer)  # an answer: let through


def test_a_turn_and_its_sequel_are_read_together():
    ctx = ChatContext()
    ctx.add_message(role="assistant", content="તમારું નામ શું છે?")
    ctx.add_message(role="user", content="રમેશ")
    ctx.add_message(role="user", content="પટેલ")
    assert words_since_agent_spoke(ctx) == "રમેશ પટેલ"
    assert last_agent_line(ctx) == "તમારું નામ શું છે?"
    assert words_since_agent_spoke(ChatContext()) == "" and last_agent_line(ChatContext()) == ""
