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
import time

import pytest
from dotenv import load_dotenv

from agent.llm_setup import build_llm
from agent.survey.flow import Reading, Survey
from agent.survey.reader import AnswerReader
from agent.survey.script import CHECK_IN, QUESTIONS

load_dotenv()
pytestmark = [
    pytest.mark.skipif(
        not (os.getenv("GROQ_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        reason="needs GROQ_API_KEY or GOOGLE_API_KEY in agent/.env",
    ),
    # One event loop for the module: the reader's LLM client is shared, and its connection dies with
    # the loop it was opened on ("Event loop is closed" on every test after the first).
    pytest.mark.asyncio(loop_scope="module"),
]
# Groq's free tier allows 8,000 tokens a minute per model, about four readings: without a pause the
# later cases hit the limit and fall back to the rules, which measures nothing. 0 when you pay.
PAUSE_SECONDS = float(os.getenv("EVAL_PAUSE_SECONDS", "15"))


@pytest.fixture(autouse=True)
def pause_between_cases():
    yield
    time.sleep(PAUSE_SECONDS)


# (question asked, what they said, intent, values that must be in the reading)
CASES = [
    ("name", "મારું નામ રમેશભાઈ પટેલ છે", "answer", {"name": "રમેશભાઈ પટેલ"}),
    ("name", "હું સીતાબેન બોલું છું", "answer", {"name": "સીતાબેન"}),
    ("name", "Ramesh", "answer", {"name": "રમેશ"}),
    ("name", "હા બોલો ને", "acknowledge", {}),
    ("name", "તમે કોણ બોલો છો?", "question", {}),
    ("name", "હમણાં ટાઈમ નથી, સાંજે ફોન કરજો", "busy", {}),
    ("name", "મારે કંઈ નથી કહેવું", "refuse", {}),
    ("name", "રમેશ પટેલ, ઉંમર પચાસ વર્ષ", "answer", {"name": "રમેશ પટેલ", "age": 50}),
    ("name", "હું સીતાબેન, સાઠ વર્ષની", "answer", {"name": "સીતાબેન", "age": 60}),
    ("age", "મારી ઉંમર પિસ્તાલીસ વર્ષ છે", "answer", {"age": 45}),
    ("age", "maari umar pachaas", "answer", {"age": 50}),
    ("age", "બાસઠ વર્ષ થયા, ગામ ખાંભા", "answer", {"age": 62, "village": "ખાંભા"}),
    ("village", "હું ખેતી કરું છું", "wrong_answer", {}),
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


# (answers so far, question asked, the agent's last words, what they said, intent, values that must be
# in the reading). The words that came before decide these: the same name is a correction right after
# a wrong one was said back, and a wrong answer when it's only said again.
IN_CONTEXT = [
    # A taluka is often named after its main village: the same name to the taluka question is an answer.
    (
        {"name": "રમેશ", "age": 45, "village": "ખાંભા"},
        "taluka",
        "સરસ, ખાંભા. તાલુકો કયો છે?",
        "ખાંભા",
        "answer",
        {"taluka": "ખાંભા"},
    ),
    (
        {"name": "રમેશ", "age": 45, "village": "ખાંભા"},
        "taluka",
        "સરસ, ખાંભા. તાલુકો કયો છે?",
        "ખાંભા જ",
        "answer",
        {"taluka": "ખાંભા"},
    ),
    ({"name": "રમેશ પટેલ"}, "age", "આભાર, રમેશ પટેલ. તમારી ઉંમર કેટલી છે?", "રમેશ પટેલ", "wrong_answer", {}),
    ({"name": "રમેશ પટેલ"}, "age", QUESTIONS["age"].wrong, "મારું નામ રમેશ પટેલ", "wrong_answer", {}),
    ({"name": "મહેશ"}, "age", "આભાર, મહેશ. તમારી ઉંમર કેટલી છે?", "મહેશ નહીં, રમેશ", "answer", {"name": "રમેશ"}),
    (
        {"name": "રમેશ", "age": 45},
        "village",
        "45 વર્ષ, ઠીક છે. તમારું ગામ કયું છે?",
        "પિસ્તાલીસ",
        "wrong_answer",
        {},
    ),
    (
        {"name": "રમેશ", "age": 45, "village": "ખાંભા"},
        "taluka",
        "સરસ, ખાંભા. તાલુકો કયો છે?",
        "ગામ ખાંભા",
        "wrong_answer",
        {},
    ),
]


@pytest.mark.parametrize(("known", "field", "last_line", "said", "intent", "values"), IN_CONTEXT)
async def test_the_llm_tells_a_correction_from_a_wrong_answer(
    reader, known, field, last_line, said, intent, values
):
    survey = Survey()
    survey.opening()
    survey.respond(Reading("answer", known))
    survey.asked = field
    reading: Reading = await reader.read(survey, said, last_line=last_line)
    assert reading.intent == intent, reading
    for key, expected in values.items():
        assert reading.values.get(key) == expected, reading
