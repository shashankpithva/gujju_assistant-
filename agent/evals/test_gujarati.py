"""Gujarati conversations with the real LLM. Opt-in: 120+ scenarios use real quota.

    uv run pytest evals/test_gujarati.py -v
    uv run pytest evals/test_gujarati.py -k code_switch          # one metric
    uv run python scripts/gujarati/eval_report.py                # the scores by metric

Each scenario in gujarati/scenarios.jsonl runs against the sample restaurant with the real tools.
It checks which tools ran and with what arguments, what must never be said, the style rules, and
(with Gujarati in mind) whether a judge model agrees the reply did its job. Every run is appended to
evals/results/, so runs under different LLMs can be compared.

A judge model can tell whether a reply answered the question. It can't tell whether it sounds like
a native speaker: only people can, on the audio (docs/gujarati/README.md).
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotenv import load_dotenv
from livekit.agents import AgentSession, mock_tools

from agent.api_client import SAMPLE_RESTAURANT_PHONE, SampleRestaurantAPI
from agent.facts import load_facts
from agent.gujarati.lines import GujaratiLines
from agent.gujarati.style import check_line, repeated_openers
from agent.main import build_llm
from agent.prompts import build_instructions
from agent.tools import CallState, Receptionist

from .conftest import NOW, called

load_dotenv()

SCENARIOS = [
    json.loads(line)
    for line in (Path(__file__).parent / "gujarati/scenarios.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
RESULTS = Path(__file__).parent / "results/gujarati.jsonl"


@pytest.fixture
async def gu_call():
    api = SampleRestaurantAPI(now=lambda: NOW)
    restaurant = await api.get_restaurant_by_number(SAMPLE_RESTAURANT_PHONE)
    state = CallState(api=api, restaurant=restaurant, call_id="eval", language="gu", gu=GujaratiLines("male"))
    llm, label = build_llm()
    async with llm, AgentSession[CallState](llm=llm, userdata=state) as session:
        with mock_tools(Receptionist, {"end_call": lambda: "Call ended."}):
            agent = Receptionist(state)
            await session.start(agent)
            facts = await load_facts(api, restaurant, "gu")
            await agent.update_instructions(
                build_instructions(
                    restaurant, caller_id_known=False, language="gu", facts=facts.text if facts else None
                )
            )
            yield SimpleNamespace(session=session, state=state, api=api, label=label)


def _args_of(result, tool: str) -> list[dict]:
    calls = [e.item for e in result.events if e.type == "function_call" and e.item.name == tool]
    return [json.loads(c.arguments or "{}") for c in calls]


def _save(row: dict) -> None:
    RESULTS.parent.mkdir(exist_ok=True)
    with RESULTS.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: f"{s['metric']}-{s['id']}")
async def test_scenario(scenario, gu_call, judge):
    results, replies, tools = [], [], []
    started = time.perf_counter()
    for words in scenario["say"]:
        result = await gu_call.session.run(user_input=words)
        results.append(result)
        tools += called(result)
        replies += [
            e.item.text_content or ""
            for e in result.events
            if e.type == "message" and e.item.role == "assistant"
        ]
    failures = []
    for tool in scenario.get("must", []):
        if tool not in tools:
            failures.append(f"didn't call {tool}")
    for tool in scenario.get("not", []):
        if tool in tools:
            failures.append(f"called {tool}")
    for tool, wanted in scenario.get("args", {}).items():
        seen = [args for result in results for args in _args_of(result, tool)]
        for key, value in wanted.items():
            if not any(args.get(key) == value for args in seen):
                failures.append(f"{tool} never got {key}={value!r}: {seen}")
    if name := scenario.get("name"):
        passed = [a.get("guest_name") or "" for r in results for a in _args_of(r, "prepare_booking")]
        if not any(name in given for given in passed):
            failures.append(f"name {name!r} not passed on: {passed}")
    text = " ".join(replies)
    for word in scenario.get("forbid", []):
        if word in text:
            failures.append(f"said {word!r}")
    style = [str(p) for reply in replies for p in check_line(reply)]
    judged = None
    if intent := scenario.get("judge"):
        try:
            await results[-1].expect.contains_message(role="assistant").judge(judge, intent=intent)
            judged = True
        except AssertionError as e:
            judged = False
            failures.append(f"judge: {e}")
    _save(
        {
            "at": datetime.now(UTC).isoformat(),
            "model": gu_call.label,
            "id": scenario["id"],
            "metric": scenario["metric"],
            "passed": not failures,
            "failures": failures,
            "style": style,
            "repeated_openers": repeated_openers(replies),
            "judged": judged,
            "seconds": round(time.perf_counter() - started, 2),
            "said": scenario["say"],
            "replies": replies,
            "tools": tools,
        }
    )
    assert not failures, failures


@pytest.fixture(autouse=True)
def _needs_a_key():
    if not (os.getenv("GROQ_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        pytest.skip("GROQ_API_KEY or GOOGLE_API_KEY not set in agent/.env")
