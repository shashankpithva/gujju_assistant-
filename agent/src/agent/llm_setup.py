"""The LLM chain: Groq first (fastest on the free tier), Gemini behind it, each model its own budget.

On a call the LLM only reads answers (survey/reader.py), one small request per turn, so the chain's
job is to always have a model that answers: a rate limit or an outage moves the request to the next
model at once instead of dropping the turn.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from livekit.agents import llm
from livekit.plugins import google, groq

# A runaway guard, not a length limit: a reading is a short function call. gpt-oss and Gemini count
# their hidden reasoning against this cap, so a tight cap could cut the call off.
MAX_REPLY_TOKENS = 600

# Groq's free tier counts its per-minute and per-day token limits per model, so each model in this
# list is a separate budget. gpt-oss-120b first: as fast as 20b here and better with Gujarati.
DEFAULT_GROQ_MODELS = "openai/gpt-oss-120b,openai/gpt-oss-20b"

# A model that failed (usually on a rate limit) sits out this long, then the next real request tries
# it again. Groq's per-minute windows reopen within seconds.
RETRY_FAILED_LLM_AFTER = 20.0


def groq_models() -> list[str]:
    return [m.strip() for m in os.getenv("GROQ_MODELS", DEFAULT_GROQ_MODELS).split(",") if m.strip()]


def groq_llm(model: str | None = None) -> llm.LLM:
    # The plugin sets reasoning_effort="low" for gpt-oss models.
    return groq.LLM(
        model=model or groq_models()[0], max_completion_tokens=MAX_REPLY_TOKENS, parallel_tool_calls=False
    )


def gemini_llm() -> llm.LLM:
    # Thinking adds latency before the first token. Gemini 3+ takes a level, and the lowest
    # accepted level varies by model: 3.5 Flash-Lite takes "minimal", 3.8 Flash needs "low".
    return google.LLM(
        model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        thinking_config={"thinking_level": os.getenv("GEMINI_THINKING_LEVEL", "minimal")},
        max_output_tokens=MAX_REPLY_TOKENS,
    )


class NoProbeFallbackAdapter(llm.FallbackAdapter):
    """LiveKit's FallbackAdapter without its recovery probes.

    To learn whether a failed model works again, the adapter re-sends the whole failed request in the
    background and throws the answer away. On the free tiers that spends a request's worth of tokens
    from the per-minute budget that just ran out. Here a failed model rejoins the chain after
    RETRY_FAILED_LLM_AFTER seconds, and the next real request finds out.
    """

    def chat(self, **kwargs: Any) -> llm.LLMStream:
        stream = super().chat(**kwargs)
        # Private hook, replaced before the stream's task first runs; tests/test_llm_setup.py pins it.
        stream._try_recovery = self._rejoin_later  # type: ignore[attr-defined]
        return stream

    def _rejoin_later(self, failed: llm.LLM) -> None:
        status = self._status[self._llm_instances.index(failed)]
        if status.recovering_task is None or status.recovering_task.done():
            status.recovering_task = asyncio.create_task(self._rejoin(status))

    @staticmethod
    async def _rejoin(status: Any) -> None:
        await asyncio.sleep(RETRY_FAILED_LLM_AFTER)
        status.available = True


def build_llm() -> tuple[llm.LLM, str]:
    """Every configured LLM in order, LLM_PROVIDER's first (Groq by default: the fastest).

    Returns the LLM and a label for the logs.
    """
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider not in ("groq", "gemini"):
        raise ValueError(f"LLM_PROVIDER must be 'gemini' or 'groq', got {provider!r}")
    groqs = [groq_llm(m) for m in groq_models()] if os.getenv("GROQ_API_KEY") else []
    geminis = [gemini_llm()] if os.getenv("GOOGLE_API_KEY") else []
    chain = groqs + geminis if provider == "groq" else geminis + groqs
    if not chain:
        raise RuntimeError("Set GROQ_API_KEY and/or GOOGLE_API_KEY in agent/.env")
    label = chain[0].model + (f" (fallback {', '.join(m.model for m in chain[1:])})" if chain[1:] else "")
    if len(chain) == 1:
        return chain[0], label
    # Each attempt's timeout becomes Gemini's request deadline, and Google rejects anything under
    # 10 s ("Minimum allowed deadline is 10s"), which would make every fallback request fail. The
    # reader gives up sooner than that anyway (survey/reader.py) and reads the turn with its rules.
    return NoProbeFallbackAdapter(chain, attempt_timeout=10.0), label
