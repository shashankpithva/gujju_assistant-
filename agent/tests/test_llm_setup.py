import asyncio

from livekit.agents import DEFAULT_API_CONNECT_OPTIONS, APIStatusError, llm
from livekit.agents.llm import ChatChunk, ChatContext, ChoiceDelta
from livekit.plugins import google

import agent.llm_setup as llm_setup
from agent.llm_setup import NoProbeFallbackAdapter, build_llm, groq_llm


def test_groq_is_primary_with_gemini_as_fallback_when_both_keys_are_set(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    monkeypatch.delenv("GROQ_MODELS", raising=False)
    session_llm, label = build_llm()
    assert isinstance(session_llm, NoProbeFallbackAdapter)
    assert label == "openai/gpt-oss-120b (fallback openai/gpt-oss-20b, gemini-3.5-flash-lite)"
    # Becomes Gemini's request deadline; Google rejects deadlines under 10 s.
    assert session_llm._attempt_timeout >= 10

    monkeypatch.delenv("GOOGLE_API_KEY")
    monkeypatch.setenv("GROQ_MODELS", "openai/gpt-oss-20b")
    session_llm, label = build_llm()
    assert not isinstance(session_llm, llm.FallbackAdapter)
    assert not isinstance(session_llm, google.LLM)
    assert label == "openai/gpt-oss-20b"


def test_gemini_can_go_first(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    _, label = build_llm()
    assert label.startswith("gemini-")


def test_no_keys_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    try:
        build_llm()
    except RuntimeError as e:
        assert "GROQ_API_KEY" in str(e)
    else:
        raise AssertionError("expected an error")


def test_groq_makes_one_tool_call_per_reply(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    assert groq_llm()._opts.parallel_tool_calls is False


class FakeLLM(llm.LLM):
    """Answers with its own name, or fails with a 429 while `failing`; counts the requests it gets."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name
        self.failing = False
        self.requests = 0

    @property
    def model(self) -> str:
        return self._name

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **_):
        self.requests += 1
        return FakeStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class FakeStream(llm.LLMStream):
    async def _run(self) -> None:
        if self._llm.failing:
            raise APIStatusError("rate limited", status_code=429, retryable=False)
        delta = ChoiceDelta(role="assistant", content=self._llm.model)
        self._event_ch.send_nowait(ChatChunk(id="1", delta=delta))


async def answer(adapter: llm.LLM) -> str:
    async with adapter.chat(chat_ctx=ChatContext.empty()) as stream:
        return "".join([chunk.delta.content async for chunk in stream if chunk.delta and chunk.delta.content])


async def test_a_failed_model_sits_out_then_rejoins_without_probe_requests(monkeypatch):
    monkeypatch.setattr(llm_setup, "RETRY_FAILED_LLM_AFTER", 0.2)
    primary, backup = FakeLLM("primary"), FakeLLM("backup")
    adapter = NoProbeFallbackAdapter([primary, backup], attempt_timeout=10.0)

    primary.failing = True  # e.g. its tokens-per-minute budget ran out
    assert await answer(adapter) == "backup"
    assert await answer(adapter) == "backup"  # sitting out: not even tried
    await asyncio.sleep(0.05)
    assert primary.requests == 1  # LiveKit's adapter would re-send the request in the background

    primary.failing = False
    await asyncio.sleep(0.25)
    assert await answer(adapter) == "primary"  # back after the pause, on a real request
    assert primary.requests == 2
