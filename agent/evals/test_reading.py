"""How well the real LLM reads Gujarati answers: the one job it has on a call.

Uses API quota (one request per case), so it isn't part of CI. Run it with your keys in agent/.env,
and again after changing the reader's instructions or the model:

    uv run pytest evals -v
    GROQ_MODELS=openai/gpt-oss-20b uv run pytest evals -v      # compare another model
    LLM_PROVIDER=gemini uv run pytest evals -v

Each case is something a person might really say, as speech-to-text would write it, with the
question that was just asked.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from agent.llm_setup import build_llm
from agent.survey.flow import Reading, Survey
from agent.survey.reader import AnswerReader
from agent.survey.script import CHECK_IN, QUESTIONS

load_dotenv()
pytestmark = pytest.mark.skipif(
    not (os.getenv("GROQ_API_KEY") or os.getenv("GOOGLE_API_KEY")),
    reason="needs GROQ_API_KEY or GOOGLE_API_KEY in agent/.env",
)

# (question asked, what they said, intent, values that must be in the reading)
CASES = [
    ("name", "મારું નામ રમેશભાઈ પટેલ છે", "answer", {"name": "રમેશભાઈ પટેલ"}),
    ("name", "હું સીતાબેન બોલું છું", "answer", {"name": "સીતાબેન"}),
    ("name", "Ramesh", "answer", {"name": "રમેશ"}),
    ("name", "હા બોલો ને", "acknowledge", {}),
    ("name", "તમે કોણ બોલો છો?", "question", {}),
    ("name", "હમણાં ટાઈમ નથી, સાંજે ફોન કરજો", "busy", {}),
    ("name", "મારે કંઈ નથી કહેવું", "refuse", {}),
    ("village", "અમારું ગામ ખાંભા", "answer", {"village": "ખાંભા"}),
    ("village", "ખાંભા, તાલુકો ખાંભા ને જિલ્લો અમરેલી", "answer", {"village": "ખાંભા", "district": "અમરેલી"}),
    ("taluka", "ના ના, ગામ ખાંભા નહીં, ખંભાળિયા", "answer", {"village": "ખંભાળિયા"}),
    ("taluka", "ધ્રાંગધ્રા", "answer", {"taluka": "ધ્રાંગધ્રા"}),
    ("district", "સુરેન્દ્રનગર જિલ્લો", "answer", {"district": "સુરેન્દ્રનગર"}),
    ("district", "શું? ફરીથી બોલો", "repeat", {}),
    ("water_supply", "હા, નળમાં આવે છે", "answer", {"water_supply": True}),
    ("water_supply", "ના ભાઈ, નથી આવતું", "answer", {"water_supply": False}),
    ("water_supply", "હા આવે છે ને, રોજ સવારે", "answer", {"water_supply": True, "frequency_days": 1.0}),
    ("frequency", "એકાંતરે આવે છે", "answer", {"frequency_days": 2.0}),
    ("frequency", "ત્રણ દિવસે એક વાર", "answer", {"frequency_days": 3.0}),
    ("frequency", "અઠવાડિયામાં એક જ વાર", "answer", {"frequency_days": 7.0}),
    ("duration", "માંડ અડધો કલાક", "answer", {"duration_minutes": 30}),
    ("duration", "સવારે છ થી આઠ", "answer", {"duration_minutes": 120}),
    ("duration", "એક દોઢ કલાક જેવું", "answer", {}),  # 60 or 90: either is a fair reading
    ("duration", "એક મિનિટ, હું મમ્મીને પૂછી લઉં", "wait", {}),
]


@pytest.fixture(scope="module")
def reader() -> AnswerReader:
    model, _ = build_llm()
    return AnswerReader(model, timeout=15)


@pytest.mark.parametrize(("field", "said", "intent", "values"), CASES)
async def test_the_llm_reads_the_answer(reader, field, said, intent, values):
    survey = Survey()
    survey.opening()
    survey.asked = field
    reading: Reading = await reader.read(survey, said, last_line=QUESTIONS[field].ask)
    assert reading.source in ("llm", "rules")
    assert reading.intent == intent, reading
    for key, expected in values.items():
        assert reading.values.get(key) == expected, reading


async def test_yes_to_can_you_hear_me_is_not_taken_as_water(reader):
    survey = Survey()
    survey.opening()
    survey.asked = "water_supply"
    reading = await reader.read(survey, "હા, સંભળાય છે", last_line=CHECK_IN)
    assert "water_supply" not in reading.values, reading
