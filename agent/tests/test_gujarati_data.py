"""The dataset, eval scenarios and prompt budget stay honest. No API keys needed."""

import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest
from livekit.agents import AgentSession, llm
from livekit.agents.llm import ChatChunk, ChoiceDelta

from agent.gujarati.lines import GujaratiLines
from agent.gujarati.style import check_line, repeated_openers
from agent.prompts import build_instructions
from agent.tools import CallState, Receptionist
from evals.gujarati_metrics import char_errors, digits_match, kept_words, word_errors

AGENT = Path(__file__).resolve().parents[1]
DATASET = AGENT / "data/gujarati/conversations.jsonl"
SCENARIOS = AGENT / "evals/gujarati/scenarios.jsonl"
STT_SENTENCES = AGENT / "evals/gujarati/stt_sentences.jsonl"


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_module():
    spec = importlib.util.spec_from_file_location(
        "build_dataset", AGENT / "scripts/gujarati/build_dataset.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The dataset -----------------------------------------------------------------------------------


def test_the_dataset_is_big_enough_and_up_to_date():
    module = build_module()
    records, problems = module.build()
    assert problems == []
    assert len(records) >= 500
    assert module.as_jsonl(records) == DATASET.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_every_requested_kind_of_conversation_is_there():
    records = load(DATASET)
    categories = Counter(r["category"] for r in records)
    wanted = [
        "greeting", "booking", "code_mix", "correction", "numbers_names", "menu_food", "follow_up",
        "register", "regional", "phone_realism", "everyday", "callback_info",
    ]  # fmt: skip
    for category in wanted:
        assert categories[category] >= 5, category
    assert Counter(r["speaker"] for r in records)["elderly"] >= 20
    assert Counter(r["speaker"] for r in records)["young"] >= 20
    assert Counter(r["register"] for r in records)["formal"] >= 15
    assert {"light", "heavy"} <= {r["mix"] for r in records}


def test_no_record_claims_to_be_real_or_reviewed():
    """The dataset is synthetic. Nothing here may say otherwise until a person has reviewed it."""
    for record in load(DATASET):
        provenance = record["provenance"]
        assert provenance["source"] == "synthetic_llm_authored"
        assert provenance["real_speech"] is False
        if provenance["native_review"] != "pending":
            assert provenance["reviewer"], record["id"]


def test_regional_speech_is_marked_as_an_approximation():
    for record in load(DATASET):
        if record["region"] != "standard":
            assert record["region"].endswith("_approx"), record["id"]
            assert record["provenance"]["region_verified"] is False


def test_the_agent_never_imitates_a_dialect():
    dialect = ("મળહે", "હમજાતું", "ચ્યોં", "ચ્યમ", "હેંડો", "ઓંય", "હાંજે")
    for record in load(DATASET):
        for turn in record["turns"]:
            if turn["role"] == "agent":
                assert not any(word in turn["text"] for word in dialect), turn["text"]


def test_the_examples_from_the_brief_are_in_the_dataset():
    text = DATASET.read_text(encoding="utf-8")
    wanted = [
        "નમસ્તે, કેમ છો? તમારી સાથે થોડી માહિતી અંગે વાત કરવી હતી. અત્યારે વાત કરવાનો સમય છે?",
        "તમારું નામ શું છે?",
        "તમે અત્યારે ક્યાં રહો છો?",
        "હું હાલમાં office માં છું.",
        "મને tomorrow call કરજો.",
        "મારું business અમદાવાદમાં છે.",
        "હું અત્યારે થોડો busy છું.",
        "મારો address WhatsApp કરી દઈશ.",
    ]
    for line in wanted:
        assert line in text, line


# The style rules -------------------------------------------------------------------------------


def test_the_robotic_sentence_from_the_brief_fails_the_style_rules():
    problems = check_line("નમસ્કાર. હું તમને માહિતી એકત્રિત કરવા માટે સંપર્ક કરી રહ્યો છું.")
    assert {p.rule for p in problems} == {"bookish"}


def test_the_natural_sentence_from_the_brief_passes():
    assert check_line("નમસ્તે, કેમ છો? તમારી સાથે થોડી માહિતી અંગે વાત કરવી હતી. અત્યારે વાત કરવાનો સમય છે?") == []


@pytest.mark.parametrize(
    ("line", "rule"),
    [
        ("તું ક્યારે આવીશ?", "intimate_pronoun"),
        ("તમારું બુકિંગ કરવામાં આવશે.", "passive"),
        ("તમારું table તૈયાર છે.", "latin_script"),
        ("સારું, સમજી ગઈ.", "wrong_gender"),
        ("કેટલા જણ? કયો દિવસ?", "two_questions"),
        ("ટેબલ " * 30, "too_long"),
    ],
)
def test_style_rules(line, rule):
    assert rule in {p.rule for p in check_line(line)}


def test_a_woman_voice_is_held_to_the_other_form():
    assert check_line("સારું, સમજી ગઈ.", gender="female") == []
    assert "wrong_gender" in {p.rule for p in check_line("સારું, સમજી ગયો.", gender="female")}


def test_saying_the_same_acknowledgement_twice_running_is_counted():
    assert repeated_openers(["સરસ, ચાર જણ.", "સરસ, કયા દિવસે?", "બરાબર."]) == 1
    assert repeated_openers(["સરસ.", "બરાબર.", "સરસ."]) == 0


# The eval scenarios ----------------------------------------------------------------------------


def test_there_are_at_least_100_scenarios_across_every_metric():
    scenarios = load(SCENARIOS)
    assert len(scenarios) >= 100
    assert len({s["id"] for s in scenarios}) == len(scenarios)
    metrics = Counter(s["metric"] for s in scenarios)
    wanted = [
        "comprehension", "code_switch", "names", "numbers", "relevance", "consistency", "safety",
        "goodbye", "regional",
    ]  # fmt: skip
    for metric in wanted:
        assert metrics[metric] >= 5, metric


def test_scenarios_only_name_real_tools():
    tools = {t.id for t in Receptionist().tools}
    for scenario in load(SCENARIOS):
        assert scenario["say"]
        assert "must" in scenario or "not" in scenario or "judge" in scenario or "name" in scenario
        assert set(scenario.get("must", [])) <= tools, scenario["id"]
        assert set(scenario.get("not", [])) <= tools, scenario["id"]
        assert set(scenario.get("args", {})) <= tools, scenario["id"]


def test_stt_sentences_cover_each_group():
    sentences = load(STT_SENTENCES)
    assert len(sentences) >= 50
    groups = Counter(s["group"] for s in sentences)
    for group in ("code_mix", "names", "places", "numbers", "everyday", "regional_approx"):
        assert groups[group] >= 5, group


# Scoring speech-to-text ------------------------------------------------------------------------


def test_the_same_word_in_two_scripts_is_not_an_error():
    assert word_errors("હું હાલમાં office માં છું.", "હું હાલમાં ઓફિસ માં છું") == (0, 5)


def test_gujarati_and_ascii_digits_are_the_same():
    assert word_errors("૯૮ જણ", "98 જણ") == (0, 2)


def test_a_wrong_word_counts_once():
    assert word_errors("કાલે ચાર જણ", "કાલે પાંચ જણ") == (1, 3)


def test_character_errors_are_gentler_than_word_errors_on_a_suffix():
    errors, total = char_errors("અમદાવાદમાં", "અમદાવાદ માં")
    assert errors == 1 and total == 10


def test_the_words_that_matter_are_scored_on_their_own():
    assert kept_words(["જિજ્ઞા", "ત્રિવેદી"], "નામ જિજ્ઞા ત્રિવેદી લખો") == (2, 2)
    assert kept_words(["જિજ્ઞા", "ત્રિવેદી"], "નામ ગીતા ત્રિવેદી લખો") == (1, 2)


def test_digits_are_compared_however_they_were_written():
    assert digits_match("9825012345", "નવ આઠ બે પાંચ શૂન્ય એક બે ત્રણ ચાર પાંચ")
    assert digits_match("9825012345", "98250 12345")
    assert not digits_match("9825012345", "98250 1234")


# The prompt budget -----------------------------------------------------------------------------


def test_the_gujarati_prompt_stays_near_the_english_one(restaurant):
    """Every turn resends it, against the free tier's tokens per minute. Tokens need tiktoken, so this
    guards the size in characters: the script's share of tokens is in docs/gujarati/README.md."""
    english = build_instructions(restaurant, caller_id_known=False)
    gujarati = build_instructions(restaurant, caller_id_known=False, language="gu")
    assert len(gujarati) < 2.4 * len(english)


# A whole turn through a real session, with a stand-in LLM --------------------------------------


class ScriptedLLM(llm.LLM):
    """Answers with fixed text; counts requests, so a turn that should skip the LLM can prove it."""

    def __init__(self, reply: str = "") -> None:
        super().__init__()
        self.reply = reply
        self.requests = 0

    @property
    def model(self) -> str:
        return "scripted"

    def chat(self, *, chat_ctx, tools=None, conn_options=None, **_):
        from livekit.agents import DEFAULT_API_CONNECT_OPTIONS

        self.requests += 1
        return ScriptedStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options or DEFAULT_API_CONNECT_OPTIONS,
        )


class ScriptedStream(llm.LLMStream):
    async def _run(self) -> None:
        delta = ChoiceDelta(role="assistant", content=self._llm.reply)
        self._event_ch.send_nowait(ChatChunk(id="1", delta=delta))


@pytest.fixture
def gu_state(api, restaurant) -> CallState:
    return CallState(api=api, restaurant=restaurant, call_id="t", language="gu", gu=GujaratiLines("male"))


async def test_a_gujarati_goodbye_hangs_up_without_asking_the_llm(gu_state):
    scripted = ScriptedLLM()
    async with scripted, AgentSession[CallState](llm=scripted, userdata=gu_state) as session:
        await session.start(Receptionist(gu_state))
        result = await session.run(user_input="આવજો")
    assert [e.item.name for e in result.events if e.type == "function_call"] == ["end_call"]
    assert scripted.requests == 0


async def test_a_false_booking_claim_never_reaches_the_caller_in_a_real_session(gu_state):
    scripted = ScriptedLLM("તમારું ટેબલ બુક થઈ ગયું.")
    async with scripted, AgentSession[CallState](llm=scripted, userdata=gu_state) as session:
        await session.start(Receptionist(gu_state))
        result = await session.run(user_input="ટેબલ બુક કરી દો")
    said = " ".join(e.item.text_content or "" for e in result.events if e.type == "message")
    assert "બુક થઈ ગયું" not in said
    assert "હજી થયું નથી" in said
