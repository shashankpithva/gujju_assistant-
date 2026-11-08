"""Stand-ins for the services a call talks to, so the tests need no keys and no network."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest
from livekit.agents import DEFAULT_API_CONNECT_OPTIONS, APIStatusError, llm
from livekit.agents.llm import ChatChunk, ChoiceDelta, FunctionToolCall


def said_in(chat_ctx: llm.ChatContext) -> str:
    """The person's words, out of the turn the reader describes to the LLM."""
    text = chat_ctx.items[-1].text_content or ""
    return text.split('What the person said: "', 1)[1].rsplit('"', 1)[0]


class ScriptedLLM(llm.LLM):
    """Answers each turn with the record_answer arguments a model would give for the words in it.

    `answers` maps what the person said to those arguments, or is a function of the words. `fail`
    makes every request fail with a rate limit, like a free tier that has run out.
    """

    def __init__(self, answers: dict[str, dict] | Callable[[str], dict] | None = None, *, fail: bool = False):
        super().__init__()
        self._answers = answers or {}
        self.fail = fail
        self.delay = 0.0
        self.requests: list[llm.ChatContext] = []
        self.tool_choices: list[Any] = []

    @property
    def model(self) -> str:
        return "scripted"

    def arguments_for(self, said: str) -> dict:
        if callable(self._answers):
            return self._answers(said)
        return self._answers.get(said, {"intent": "unclear"})

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **kwargs):
        self.requests.append(chat_ctx)
        self.tool_choices.append(kwargs.get("tool_choice"))
        return _ScriptedStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class _ScriptedStream(llm.LLMStream):
    async def _run(self) -> None:
        model: ScriptedLLM = self._llm  # type: ignore[assignment]
        if model.delay:
            await asyncio.sleep(model.delay)
        if model.fail:
            raise APIStatusError("rate limited", status_code=429, retryable=False)
        arguments = json.dumps(model.arguments_for(said_in(self._chat_ctx)), ensure_ascii=False)
        call = FunctionToolCall(name="record_answer", arguments=arguments, call_id="call_1")
        self._event_ch.send_nowait(ChatChunk(id="1", delta=ChoiceDelta(role="assistant", tool_calls=[call])))


class Speech:
    """A stand-in SpeechHandle: done when finish() is called, or at once if `done`."""

    def __init__(self, text: str, *, allow_interruptions: bool = True) -> None:
        self.text = text
        self.allow_interruptions = allow_interruptions
        self.interrupted = False
        self._callbacks: list[Callable] = []
        self._done = asyncio.get_running_loop().create_future()

    def add_done_callback(self, callback: Callable) -> None:
        self._callbacks.append(callback)
        if self._done.done():
            callback(self)

    def finish(self, *, interrupted: bool = False) -> None:
        self.interrupted = interrupted
        if not self._done.done():
            self._done.set_result(None)
        for callback in self._callbacks:
            callback(self)

    def done(self) -> bool:
        return self._done.done()

    def __await__(self):
        return self._done.__await__()


class FakeSession:
    """What CallControls and main.py use of an AgentSession: events, say, interrupt, shutdown."""

    def __init__(self) -> None:
        self.handlers: dict[str, list[Callable]] = {}
        self.speeches: list[Speech] = []
        self.shut_down = False
        self.agent_state = "listening"
        self.user_state = "listening"
        self.finish_speech_at_once = True

    @property
    def said(self) -> list[str]:
        return [s.text for s in self.speeches]

    def on(self, event: str, handler: Callable) -> None:
        self.handlers.setdefault(event, []).append(handler)

    def off(self, event: str, handler: Callable) -> None:
        self.handlers.get(event, []).remove(handler)

    def emit(self, event: str, ev: Any) -> None:
        for handler in list(self.handlers.get(event, [])):
            handler(ev)

    def say(self, text: str, *, allow_interruptions: bool = True, **_: Any) -> Speech:
        speech = Speech(text, allow_interruptions=allow_interruptions)
        self.speeches.append(speech)
        if self.finish_speech_at_once:
            speech.finish()
        return speech

    async def interrupt(self, **_: Any) -> None:
        return None

    def shutdown(self) -> None:
        self.shut_down = True


class FakeJob:
    def __init__(self) -> None:
        self.room_deleted = False
        self.shutdown_reason: str | None = None

    async def delete_room(self) -> None:
        self.room_deleted = True

    def shutdown(self, reason: str = "") -> None:
        self.shutdown_reason = reason


@pytest.fixture
def scratch(tmp_path):
    return tmp_path
